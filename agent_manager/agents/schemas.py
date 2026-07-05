from enum import StrEnum
from typing import Annotated, Any, NotRequired, Optional, TypedDict

from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, field_validator

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


class RoutingDecision(BaseModel):
    next_node: str | None

    @field_validator("next_node")
    @classmethod
    def normalize_next_node(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.lower() in ("null", "none", "end"):
            return None

        return v


class Node(StrEnum):
    COMPACTION = "compaction"
    ORCHESTRATOR = "orchestrator"
    WEB_GIS_EXPERT = "web_gis_expert"
    RESPONDER = "responder"
    UI_EXPERT = "ui_expert"
    CRITIC = "critic"
    # MAP_ZOOM_TO = "map_zoom_to"
    # OPEN_PROCESSING_TOOL = "open_processing_tool"


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
    prev_node: Optional[str] = None
    next_node: Optional[str] = None
    final_response: str | list[str | dict]
    ui_action: Optional[UIAction] = None
    loop_iteration: int = 0
    critique: str = ""
    critique_approved: bool = False
    conversation_summary: str = ""
