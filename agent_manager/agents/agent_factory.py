import dataclasses
import logging
from typing import cast

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import RemoveMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Overwrite
from pydantic import ValidationError

from agent_manager.agents.helpers import create_path_map
from agent_manager.constants import MAX_LOOP_ITERATIONS

from .agent import Agent
from .llm import LLMConfig, LLMFactory
from .message_helpers import get_messages_to_summarize, should_compact, trim_messages
from .prompts import (
    orchestrator_prompt,
    responder_prompt,
    summarizer_prompt,
    ui_expert_prompt,
    verifier_prompt,
    web_gis_prompt,
)
from .schemas import (
    GlobalMessageState,
    Node,
    RoutingDecision,
    UIAction,
    UIActionDecision,
)
from .tools import create_gis_layer, retrieve_from_documents, run_python

logger = logging.getLogger(__name__)


class AgentFactory:
    def __init__(self, llm_config: LLMConfig):
        self.llm_base_config: LLMConfig = dataclasses.replace(
            llm_config, temperature=None
        )

    def graph_router(self, state: GlobalMessageState) -> str | list[str]:
        if state.next_nodes:
            return list(state.next_nodes)

        return Node.RESPONDER

    async def compaction_node(self, state: GlobalMessageState, config: RunnableConfig):
        if not should_compact(state.messages):
            return {}

        messages_to_summarize = get_messages_to_summarize(state.messages)
        context = messages_to_summarize

        if state.conversation_summary:
            context = [
                SystemMessage(
                    content=f"[Previous summary]:\n{state.conversation_summary}"
                )
            ] + messages_to_summarize

        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.1)
        llm = LLMFactory.create_llm(llm_config)

        try:
            response = await (summarizer_prompt | llm).ainvoke(
                {"messages": context}, config
            )
            summary = (
                response.content
                if isinstance(response.content, str)
                else str(response.content)
            )
        except Exception:
            logger.warning("Context compaction failed — keeping existing summary.")
            return {}

        messages_to_remove = get_messages_to_summarize(state.messages)
        removals = [RemoveMessage(id=m.id) for m in messages_to_remove]

        return {"messages": removals, "conversation_summary": summary}

    async def orchestrator_node(
        self, state: GlobalMessageState, config: RunnableConfig
    ):
        messages = trim_messages(state.messages, state.conversation_summary)
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.1)
        llm = LLMFactory.create_llm(llm_config)
        orchestrator_chain = orchestrator_prompt | llm.with_structured_output(
            RoutingDecision
        )

        try:
            decision = cast(
                RoutingDecision,
                await orchestrator_chain.ainvoke({"messages": messages}, config),
            )

        except (ValidationError, OutputParserException, Exception):
            decision = RoutingDecision()

        return {
            "prev_node": Overwrite([Node.ORCHESTRATOR]),
            "next_nodes": decision.next_nodes,
            "final_response": "",
        }

    async def web_gis_expert_node(
        self, state: GlobalMessageState, config: RunnableConfig
    ):
        messages = list(trim_messages(state.messages, state.conversation_summary))
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.6)
        llm = LLMFactory.create_llm(llm_config)
        llm_with_tools = llm.bind_tools(
            [run_python, create_gis_layer, retrieve_from_documents]
        )
        new_messages = []

        tool_call_iterations = 0

        while tool_call_iterations < MAX_LOOP_ITERATIONS:
            response = await (web_gis_prompt | llm_with_tools).ainvoke(
                {"messages": messages}, config
            )
            messages.append(response)
            new_messages.append(response)

            if not response.tool_calls:
                break

            tool_call_iterations += 1

            for tool_call in response.tool_calls:
                logger.info(
                    "web_gis_expert_node calling tool %r with args %r",
                    tool_call["name"],
                    tool_call["args"],
                )

                if tool_call["name"] == "create_gis_layer":
                    result = await create_gis_layer.ainvoke(
                        {**tool_call["args"], "state": state.model_dump()}, config
                    )
                elif tool_call["name"] == "retrieve_from_documents":
                    result = await retrieve_from_documents.ainvoke(
                        {**tool_call["args"], "state": state.model_dump()}, config
                    )
                else:
                    result = await run_python.ainvoke(tool_call["args"], config)
                tool_message = ToolMessage(content=result, tool_call_id=tool_call["id"])
                messages.append(tool_message)
                new_messages.append(tool_message)

        return {
            "prev_node": [Node.WEB_GIS_EXPERT],
            "messages": new_messages,
        }

    async def ui_expert_node(self, state: GlobalMessageState, config: RunnableConfig):
        messages = trim_messages(state.messages, state.conversation_summary)
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.1)
        llm = LLMFactory.create_llm(llm_config)

        chain = ui_expert_prompt | llm.with_structured_output(UIActionDecision)

        try:
            decision = cast(
                UIActionDecision,
                await chain.ainvoke({"messages": messages}, config),
            )
            ui_action = UIAction(
                type=decision.type,
                payload={"to": decision.to},
            )

        except (ValidationError, OutputParserException, Exception):
            ui_action = None

        return {
            "prev_node": [Node.UI_EXPERT],
            "ui_action": ui_action,
        }

    async def responder_node(self, state: GlobalMessageState, config: RunnableConfig):
        messages = trim_messages(state.messages, state.conversation_summary)
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.6)
        llm = LLMFactory.create_llm(llm_config)

        web_gis_ran = Node.WEB_GIS_EXPERT in state.prev_node
        ui_ran = Node.UI_EXPERT in state.prev_node

        def nav_sentence() -> str:
            app = (
                state.ui_action.payload.get("to", "the app")
                if state.ui_action
                else "the app"
            )
            return f"Navigating to {app}."

        if ui_ran and not web_gis_ran:
            content = nav_sentence()
        else:
            prompt = verifier_prompt if web_gis_ran else responder_prompt
            response = await (prompt | llm).ainvoke({"messages": messages}, config)
            content = (
                response.content
                if isinstance(response.content, str)
                else str(response.content)
            )

            if ui_ran:
                content = f"{content}\n\n{nav_sentence()}"

        return {
            "prev_node": [Node.RESPONDER],
            "final_response": content,
        }

    def build_agent(self, checkpointer) -> Agent:
        graph_builder = StateGraph(GlobalMessageState)

        # Nodes.
        graph_builder.add_node(Node.COMPACTION, self.compaction_node)
        graph_builder.add_node(Node.ORCHESTRATOR, self.orchestrator_node)
        graph_builder.add_node(Node.WEB_GIS_EXPERT, self.web_gis_expert_node)
        graph_builder.add_node(Node.UI_EXPERT, self.ui_expert_node)
        graph_builder.add_node(Node.RESPONDER, self.responder_node)
        # graph_builder.add_node(Node.CRITIC, self.critic_node)

        # Edges.
        graph_builder.add_edge(START, Node.COMPACTION)
        graph_builder.add_edge(Node.COMPACTION, Node.ORCHESTRATOR)
        graph_builder.add_edge(Node.WEB_GIS_EXPERT, Node.RESPONDER)
        graph_builder.add_edge(Node.UI_EXPERT, Node.RESPONDER)
        graph_builder.add_edge(Node.RESPONDER, END)
        # graph_builder.add_edge(Node.RESPONDER, Node.CRITIC)

        # Conditional edges.
        graph_builder.add_conditional_edges(
            Node.ORCHESTRATOR,
            self.graph_router,
            create_path_map([Node.WEB_GIS_EXPERT, Node.UI_EXPERT, Node.RESPONDER]),
        )
        # graph_builder.add_conditional_edges(
        #     Node.CRITIC,
        #     self.critic_router,
        #     create_path_map([Node.ORCHESTRATOR, END]),
        # )

        return Agent(graph_builder.compile(checkpointer=checkpointer))
