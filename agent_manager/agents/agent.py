from typing import cast

from langchain_core.exceptions import OutputParserException
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent_manager.agents.helpers import create_path_map

from .llm import LLMFactory
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
    def __init__(self, llm_config):
        self.llm = LLMFactory.create_llm(llm_config)

    def graph_router(self, state: GlobalMessageState) -> str:
        next_node = state.next_node

        if next_node == Node.WEB_GIS_EXPERT:
            return Node.WEB_GIS_EXPERT

        if next_node == Node.UI_EXPERT:
            return Node.UI_EXPERT

        return Node.RESPONDER

    async def orchestrator_node(self, state: GlobalMessageState):
        messages = trim_messages(state.messages)
        orchestrator_chain = orchestrator_prompt | self.llm.with_structured_output(
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
        response = await (web_gis_prompt | self.llm).ainvoke({"messages": messages})

        return {
            "prev_node": Node.WEB_GIS_EXPERT,
            "next_node": Node.RESPONDER,
            "messages": [response],
        }

    async def ui_expert_node(self, state: GlobalMessageState):
        messages = trim_messages(state.messages)
        chain = ui_expert_prompt | self.llm.with_structured_output(UIActionDecision)

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

        if state.prev_node == Node.UI_EXPERT:
            app = state.ui_action.payload.get("to", "the app") if state.ui_action else "the app"
            content = f"Navigating to {app}."
        else:
            prompt = verifier_prompt if state.prev_node == Node.WEB_GIS_EXPERT else responder_prompt
            response = await (prompt | self.llm).ainvoke({"messages": messages})
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

    # def map_zoom_to_node(self, state: GlobalMessageState):
    #     result = state["geocode_result"]
    #     assert result is not None

    #     return {
    #         "prev_node": Node.MAP_ZOOM_TO,
    #         "next_node": Node.ORCHESTRATOR,
    #         "ui_action": {
    #             "app": "web_gis",
    #             "type": UIActionType.MAP_ZOOM_TO,
    #             "payload": {
    #                 "latitude": result["latitude"],
    #                 "longitude": result["longitude"],
    #             },
    #         },
    #     }

    # def open_processing_tool_node(self, state: GlobalMessageState):
    #     pending = state.get("pending_processing_tool")
    #     assert pending is not None

    #     payload: dict[str, Any] = {
    #         "tool_name": pending["tool_name"],
    #         "defaults": pending.get("defaults") or {},
    #     }

    #     if pending.get("output_name"):
    #         payload["output_name"] = pending["output_name"]  # type: ignore

    #     return {
    #         "prev_node": Node.OPEN_PROCESSING_TOOL,
    #         "next_node": Node.ORCHESTRATOR,
    #         "ui_action": {
    #             "app": "web_gis",
    #             "type": UIActionType.OPEN_PROCESSING_TOOL,
    #             "payload": payload,
    #         },
    #     }

    def build_agent(self, checkpointer):
        graph_builder = StateGraph(GlobalMessageState)
        graph_builder.add_node(Node.ORCHESTRATOR, self.orchestrator_node)
        graph_builder.add_node(Node.WEB_GIS_EXPERT, self.web_gis_expert_node)
        graph_builder.add_node(Node.UI_EXPERT, self.ui_expert_node)
        graph_builder.add_node(Node.RESPONDER, self.responder_node)

        graph_builder.add_edge(START, Node.ORCHESTRATOR)
        graph_builder.add_conditional_edges(
            Node.ORCHESTRATOR,
            self.graph_router,
            create_path_map([Node.WEB_GIS_EXPERT, Node.UI_EXPERT, Node.RESPONDER]),
        )
        graph_builder.add_edge(Node.WEB_GIS_EXPERT, Node.RESPONDER)
        graph_builder.add_edge(Node.UI_EXPERT, Node.RESPONDER)
        graph_builder.add_edge(Node.RESPONDER, END)

        return graph_builder.compile(checkpointer=checkpointer)
