from typing import Optional

from pydantic import BaseModel

from agent_manager.agents.schemas import UIAction

from .constants import Role


class IncomingMessage(BaseModel):
    message: str
    context: Optional[dict]


class OutgoingMessage(BaseModel):
    id: str
    session_id: str
    message: str
    user_id: str
    role: Role
    isChunk: bool
    ui_action: Optional[UIAction] = None
