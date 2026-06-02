from enum import StrEnum

from django.db import models

MAX_MESSAGE_LENGTH = 4000
AGENT_LOCK_TIMEOUT = 120
GRAPH_TURN_TIMEOUT = 60
CHUNK_SAVE_INTERVAL = 25


class Role(StrEnum):
    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"


class ChatMessageType(StrEnum):
    MESSAGE = "message"
    ACTION = "action"
    INTERRUPT = "interrupt"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class MessageStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"
