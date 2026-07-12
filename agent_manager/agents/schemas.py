import operator
from enum import StrEnum
from typing import Annotated, Any, NotRequired, Optional, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, field_validator

from agent_manager.agents.constants import UIActionType, UIApps

# class MapZoomToPayload(TypedDict):
#     longitude: float
#     latitude: float


# class OpenProcessingToolPayload(TypedDict):
#     tool_name: str
#     defaults: dict[str, Any]
#     output_name: NotRequired[str]


class NavigationActionPayload(TypedDict):
    to: UIApps


class UIAction(BaseModel):
    app: str | None = None
    type: UIActionType
    payload: NavigationActionPayload


class UIActionDecision(BaseModel):
    type: UIActionType
    to: UIApps


class Node(StrEnum):
    COMPACTION = "compaction"
    ORCHESTRATOR = "orchestrator"
    WEB_GIS_EXPERT = "web_gis_expert"
    RESPONDER = "responder"
    UI_EXPERT = "ui_expert"
    CRITIC = "critic"
    # MAP_ZOOM_TO = "map_zoom_to"
    # OPEN_PROCESSING_TOOL = "open_processing_tool"


ROUTABLE_NODES = {Node.WEB_GIS_EXPERT.value, Node.UI_EXPERT.value}


class RoutingDecision(BaseModel):
    next_nodes: list[Node] = Field(default_factory=list)

    @field_validator("next_nodes", mode="before")
    @classmethod
    def normalize_next_nodes(cls, v: Any) -> list[str]:
        if v is None:
            return []

        if isinstance(v, str):
            v = [v]

        seen: set[str] = set()
        normalized: list[str] = []

        for item in v:
            if not isinstance(item, str):
                continue

            candidate = item.strip().lower()

            if candidate in ("", "null", "none", "end"):
                continue

            if candidate not in ROUTABLE_NODES or candidate in seen:
                continue

            seen.add(candidate)
            normalized.append(candidate)

        return normalized


class LoadedLayer(TypedDict):
    id: str
    name: str
    type: str
    dataset_id: NotRequired[str]


class PendingProcessingTool(TypedDict):
    tool_name: str
    defaults: dict[str, Any]


class CritiqueDecision(BaseModel):
    approved: bool
    critique: str


class GlobalMessageState(BaseModel):
    session_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    prev_node: Annotated[list[str], operator.add] = Field(default_factory=list)
    next_nodes: list[str] = Field(default_factory=list)
    final_response: str | list[str | dict]
    ui_action: Optional[UIAction] = None
    loop_iteration: int = 0
    critique: str = ""
    critique_approved: bool = False
    conversation_summary: str = ""
