import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Any, TypedDict, cast
from uuid import UUID

from asgiref.sync import sync_to_async
from asgiref.typing import WebSocketScope
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import SecretStr

from agent_manager.schemas import AgentStatusMessage, OutgoingMessage
from backend_projects.env_variables import EnvVariable

from .agents.agent_factory import AgentFactory
from .agents.llm import LLMConfig
from .agents.message_helpers import should_compact
from .agents.schemas import GlobalMessageState
from .constants import CHUNK_SAVE_INTERVAL, GRAPH_TURN_TIMEOUT, MAX_MESSAGE_LENGTH, Role
from .db import get_postgres_checkpointer
from .helpers import parse_incoming_message
from .models import ChatSession, Message, MessageRole, MessageStatus

logger = logging.getLogger(__name__)


class UrlRoute(TypedDict):
    args: tuple[str | int, ...]
    kwargs: dict[str, str | int | UUID]


class ChannelsWebSocketScope(WebSocketScope):
    user: Any
    url_route: UrlRoute


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        scope: ChannelsWebSocketScope = self.scope  # type: ignore
        user = scope.get("user")
        url_route = scope.get("url_route")

        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        if url_route is None:
            await self.close(code=4400)
            return

        session_id = url_route.get("kwargs", {}).get("session_id")

        if not isinstance(session_id, (str, UUID)):
            await self.close(code=4400)
            return

        self.user = cast(Any, user)
        self.session_id = str(session_id)
        self.chat_session = await self.get_chat_session(self.session_id, self.user.id)

        if self.chat_session is None:
            await self.close(code=4404)
            return

        await self.accept()

        self._exit_stack = AsyncExitStack()

        try:
            checkpointer = await self._exit_stack.enter_async_context(
                get_postgres_checkpointer()
            )
            llm_config = LLMConfig(
                model=EnvVariable.LLM_DEFAULT_MODEL.value,
                base_url=EnvVariable.LLM_BASE_URL.value,
                api_key=SecretStr("not-needed"),
                timeout=EnvVariable.LLM_TIMEOUT.value,
                temperature=EnvVariable.LLM_TEMPERATURE.value,
            )
            self._agent = AgentFactory(llm_config).build_agent(checkpointer)
        except Exception:
            logger.exception(
                "Failed to initialise agent for session %s", self.session_id
            )
            await self._exit_stack.aclose()
            await self.close(code=4500)
            return

    async def disconnect(self, _close_code):
        if hasattr(self, "_exit_stack"):
            await self._exit_stack.aclose()

        if hasattr(self, "session_id"):
            await sync_to_async(cache.delete)(f"agent:lock:{self.session_id}")

    async def receive(self, text_data):
        logger.debug(text_data)
        try:
            incoming_message = parse_incoming_message(text_data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid JSON payload."}))
            return

        message = incoming_message.message

        if not message:
            await self.send(
                text_data=json.dumps({"error": "Message content is required."})
            )
            return

        if len(message) > MAX_MESSAGE_LENGTH:
            await self.send(
                text_data=json.dumps(
                    {"error": f"Message exceeds {MAX_MESSAGE_LENGTH} character limit."}
                )
            )
            return

        # # Deduplicate retried messages from reconnecting clients.
        # client_message_id = incoming_message.message

        # if client_message_id:
        #     dedup_key = f"agent:dedup:{client_message_id}"
        #     is_new = await sync_to_async(cache.add)(dedup_key, "1", timeout=300)

        #     if not is_new:
        #         return

        # # Prevent concurrent graph runs for the same session.
        # lock_key = f"agent:lock:{self.session_id}"
        # acquired = await sync_to_async(cache.add)(
        #     lock_key, "1", timeout=AGENT_LOCK_TIMEOUT
        # )

        # if not acquired:
        #     await self.send(
        #         text_data=json.dumps(
        #             {"error": "Please wait for the current response to finish."}
        #         )
        #     )
        #     return

        saved_message = await self.create_message(
            session_id=self.session_id,
            user_id=self.user.id,
            content=message,
            role=MessageRole.USER,
        )

        await self._send_message(
            message_id=str(saved_message.id),
            role=Role.USER,
            content=saved_message.content,
        )

        # Agent Response preparation.
        saved_agent_message = await self.create_message(
            session_id=self.session_id,
            user_id=self.user.id,
            content="",
            role=MessageRole.ASSISTANT,
            status=MessageStatus.PENDING,
        )

        full_content = ""
        last_ui_action = None
        timed_out = False

        try:
            full_content, last_ui_action = await asyncio.wait_for(
                self._execute_graph(message, saved_agent_message.id),
                timeout=GRAPH_TURN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            timed_out = True
            full_content = "Request timed out. Please try again."
            logger.error("Agent graph timed out for session %s", self.session_id)

            await self._send_message(
                message_id=str(saved_agent_message.id),
                role=Role.ASSISTANT,
                content=full_content,
                is_chunk=True,
            )
        # finally:
        #     await sync_to_async(cache.delete)(lock_key)

        await self._send_message(
            message_id=str(saved_agent_message.id),
            role=Role.ASSISTANT,
            content="",
            is_chunk=False,
            ui_action=last_ui_action,
        )

        final_status = MessageStatus.FAILED if timed_out else MessageStatus.COMPLETE
        await self.update_message(saved_agent_message.id, full_content, final_status)

    async def _execute_graph(
        self,
        message: str,
        agent_message_id,
    ) -> tuple[str, dict | None]:
        return await self._stream_graph(self._agent, message, agent_message_id)

    async def _stream_graph(
        self,
        agent,
        message: str,
        agent_message_id,
    ) -> tuple[str, dict | None]:
        inputs = GlobalMessageState(
            session_id=self.session_id,
            messages=[HumanMessage(content=message)],
            prev_node=None,
            next_node=None,
            final_response="",
            ui_action=None,
        )

        config = cast(
            RunnableConfig,
            {
                "configurable": {"thread_id": self.session_id},
                "recursion_limit": 25,
            },
        )

        try:
            current_state = await agent.graph.aget_state(config)

            if current_state and should_compact(current_state.values.get("messages", [])):
                await self._send_status("compacting")
        except Exception:
            pass

        full_content = ""
        last_ui_action = None
        chunk_count = 0

        try:
            async for chunk_content, ui_action in agent.astream(inputs, config):
                full_content += chunk_content
                chunk_count += 1

                if ui_action is not None:
                    last_ui_action = ui_action

                await self._send_message(
                    message_id=str(agent_message_id),
                    role=Role.ASSISTANT,
                    content=chunk_content,
                    is_chunk=True,
                )

                if chunk_count % CHUNK_SAVE_INTERVAL == 0:
                    await self.update_message(
                        agent_message_id, full_content, MessageStatus.PENDING
                    )

        except Exception as e:
            logger.exception(
                "Agent stream error for session %s: %s", self.session_id, e
            )
            full_content = full_content or "I could not process your request right now."

            await self._send_message(
                message_id=str(agent_message_id),
                role=Role.ASSISTANT,
                content="I could not process your request right now.",
                is_chunk=True,
            )

        return full_content, last_ui_action

    async def _send_message(
        self,
        message_id: str,
        role: Role,
        content: str,
        is_chunk: bool = False,
        ui_action=None,
    ):
        await self.send(
            text_data=OutgoingMessage(
                id=message_id,
                session_id=self.session_id,
                message=content,
                user_id=str(self.user.id),
                role=role,
                isChunk=is_chunk,
                ui_action=ui_action,
            ).model_dump_json()
        )

    async def _send_status(self, status: str):
        await self.send(
            text_data=AgentStatusMessage(
                session_id=self.session_id,
                status=status,
            ).model_dump_json()
        )

    @sync_to_async
    def get_chat_session(self, session_id, user_id) -> ChatSession | None:
        try:
            return ChatSession.objects.get(id=session_id, user_id=user_id)
        except ObjectDoesNotExist:
            return None

    @sync_to_async
    def create_message(
        self, session_id, user_id, content, role, status=MessageStatus.COMPLETE
    ):
        return Message.objects.create(
            session_id=session_id,
            user_id=user_id,
            content=content,
            role=role,
            status=status,
        )

    @sync_to_async
    def update_message(self, message_id, content, status=MessageStatus.COMPLETE):
        Message.objects.filter(id=message_id).update(content=content, status=status)
