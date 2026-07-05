from enum import StrEnum

MAX_CONTEXT_MESSAGES = 20
MAX_TOOL_ITERATIONS = 5

COMPACTION_THRESHOLD = 20
RECENT_MESSAGES_TO_KEEP = 6


class UIActionType(StrEnum):
    NAVIGATE = "navigate"


class UIApps(StrEnum):
    TODO = "todo"
