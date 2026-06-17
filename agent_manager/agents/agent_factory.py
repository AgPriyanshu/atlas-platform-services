import dataclasses
from typing import cast

from langchain_core.exceptions import OutputParserException
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent_manager.agents.helpers import create_path_map

from .agent import Agent
from .llm import LLMConfig, LLMFactory
from .message_helpers import trim_messages
from .prompts import (
    orchestrator_prompt,
    responder_prompt,
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

# _TOOLS = [
#     geocode,
#     list_loaded_vector_layers,
#     list_processing_tools,
#     open_processing_tool,
# ]

# _TOOLS_BY_NAME = {t.name: t for t in _TOOLS}

# llm_with_tools = llm.bind_tools(_TOOLS)


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

    async def orchestrator_node(self, state: GlobalMessageState):
        messages = trim_messages(state.messages)
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.1)
        llm = LLMFactory.create_llm(llm_config)
        orchestrator_chain = orchestrator_prompt | llm.with_structured_output(
            RoutingDecision
        )

        try:
            decision = cast(
                RoutingDecision,
                await orchestrator_chain.ainvoke({"messages": messages}),
            )

        except (ValidationError, OutputParserException, Exception):
            decision = RoutingDecision(next_node=None)

        return {
            "prev_node": Node.ORCHESTRATOR,
            "next_node": decision.next_node,
            "final_response": "",
        }

    async def web_gis_expert_node(self, state: GlobalMessageState):
        messages = list(trim_messages(state.messages))
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.6)
        llm = LLMFactory.create_llm(llm_config)

        response = await (web_gis_prompt | llm).ainvoke({"messages": messages})

        return {
            "prev_node": Node.WEB_GIS_EXPERT,
            "next_node": Node.RESPONDER,
            "messages": [response],
        }

    async def ui_expert_node(self, state: GlobalMessageState):
        messages = trim_messages(state.messages)
        llm_config = dataclasses.replace(self.llm_base_config, temperature=0.1)
        llm = LLMFactory.create_llm(llm_config)

        chain = ui_expert_prompt | llm.with_structured_output(UIActionDecision)

        try:
            decision = cast(
                UIActionDecision,
                await chain.ainvoke({"messages": messages}),
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

    async def responder_node(self, state: GlobalMessageState):
        messages = trim_messages(state.messages)
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
            response = await (prompt | llm).ainvoke({"messages": messages})
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

    def build_agent(self, checkpointer) -> Agent:
        graph_builder = StateGraph(GlobalMessageState)

        # Nodes.
        graph_builder.add_node(Node.ORCHESTRATOR, self.orchestrator_node)
        graph_builder.add_node(Node.WEB_GIS_EXPERT, self.web_gis_expert_node)
        graph_builder.add_node(Node.UI_EXPERT, self.ui_expert_node)
        graph_builder.add_node(Node.RESPONDER, self.responder_node)

        # Edges.
        graph_builder.add_edge(START, Node.ORCHESTRATOR)
        graph_builder.add_edge(Node.WEB_GIS_EXPERT, Node.RESPONDER)
        graph_builder.add_edge(Node.UI_EXPERT, Node.RESPONDER)
        graph_builder.add_edge(Node.RESPONDER, END)

        # Conditional Edges
        graph_builder.add_conditional_edges(
            Node.ORCHESTRATOR,
            self.graph_router,
            create_path_map([Node.WEB_GIS_EXPERT, Node.UI_EXPERT, Node.RESPONDER]),
        )

        return Agent(graph_builder.compile(checkpointer=checkpointer))
