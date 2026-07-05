import dataclasses
import logging
from typing import cast

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import RemoveMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent_manager.agents.helpers import create_path_map
from agent_manager.constants import MAX_LOOP_ITERATIONS

from .agent import Agent
from .llm import LLMConfig, LLMFactory
from .message_helpers import get_messages_to_summarize, should_compact, trim_messages
from .prompts import (  # critic_prompt,
    orchestrator_prompt,
    responder_prompt,
    summarizer_prompt,
    ui_expert_prompt,
    verifier_prompt,
    web_gis_prompt,
)
from .schemas import (  # CritiqueDecision,
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

    def graph_router(self, state: GlobalMessageState) -> str:
        next_node = state.next_node

        if next_node == Node.WEB_GIS_EXPERT:
            return Node.WEB_GIS_EXPERT

        if next_node == Node.UI_EXPERT:
            return Node.UI_EXPERT

        return Node.RESPONDER

    # def critic_router(self, state: GlobalMessageState) -> str:
    #     if state.critique_approved:
    #         return END
    #
    #     return Node.ORCHESTRATOR

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

    async def orchestrator_node(self, state: GlobalMessageState, config: RunnableConfig):
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
            decision = RoutingDecision(next_node=None)

        return {
            "prev_node": Node.ORCHESTRATOR,
            "next_node": decision.next_node,
            "final_response": "",
        }

    async def web_gis_expert_node(self, state: GlobalMessageState, config: RunnableConfig):
        messages = list(trim_messages(state.messages, state.conversation_summary))
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.6)
        llm = LLMFactory.create_llm(llm_config)
        llm_with_tools = llm.bind_tools([run_python, create_gis_layer, retrieve_from_documents])
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
                tool_message = ToolMessage(
                    content=result, tool_call_id=tool_call["id"]
                )
                messages.append(tool_message)
                new_messages.append(tool_message)

        return {
            "prev_node": Node.WEB_GIS_EXPERT,
            "next_node": Node.RESPONDER,
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
            "prev_node": Node.UI_EXPERT,
            "next_node": Node.RESPONDER,
            "ui_action": ui_action,
        }

    async def responder_node(self, state: GlobalMessageState, config: RunnableConfig):
        messages = trim_messages(state.messages, state.conversation_summary)
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.6)
        llm = LLMFactory.create_llm(llm_config)

        if state.prev_node == Node.UI_EXPERT:
            app = (
                state.ui_action.payload.get("to", "the app")
                if state.ui_action
                else "the app"
            )
            content = f"Navigating to {app}."
        else:
            prompt = (
                verifier_prompt
                if state.prev_node == Node.WEB_GIS_EXPERT
                else responder_prompt
            )
            response = await (prompt | llm).ainvoke({"messages": messages}, config)
            content = (
                response.content
                if isinstance(response.content, str)
                else str(response.content)
            )

        return {
            "prev_node": Node.RESPONDER,
            "next_node": None,
            "final_response": content,
        }

    # async def critic_node(self, state: GlobalMessageState, config: RunnableConfig):
    #     if state.loop_iteration >= MAX_LOOP_ITERATIONS:
    #         return {
    #             "prev_node": Node.CRITIC,
    #             "critique_approved": True,
    #             "critique": "",
    #         }
    #
    #     messages = trim_messages(state.messages, state.conversation_summary)
    #     llm_config = dataclasses.replace(self.llm_base_config, temperature=0.1)
    #     llm = LLMFactory.create_llm(llm_config)
    #     chain = critic_prompt | llm.with_structured_output(CritiqueDecision)
    #
    #     try:
    #         decision = cast(
    #             CritiqueDecision,
    #             await chain.ainvoke(
    #                 {
    #                     "messages": messages,
    #                     "draft_response": state.final_response,
    #                 },
    #                 config,
    #             ),
    #         )
    #
    #     except (ValidationError, OutputParserException, Exception):
    #         decision = CritiqueDecision(approved=True, critique="")
    #
    #     return {
    #         "prev_node": Node.CRITIC,
    #         "critique": decision.critique,
    #         "critique_approved": decision.approved,
    #         "loop_iteration": state.loop_iteration + 1,
    #     }

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
