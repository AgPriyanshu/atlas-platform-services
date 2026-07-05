from langchain.messages import AnyMessage, HumanMessage
from langchain_core.messages import SystemMessage

from .constants import (
    COMPACTION_THRESHOLD,
    MAX_CONTEXT_MESSAGES,
    RECENT_MESSAGES_TO_KEEP,
)


def trim_messages(messages: list, summary: str = "") -> list:
    if summary:
        summary_message = SystemMessage(
            content=f"[Earlier conversation summary]:\n{summary}"
        )
        return [summary_message] + messages[-RECENT_MESSAGES_TO_KEEP:]

    return messages[-MAX_CONTEXT_MESSAGES:]


def should_compact(messages: list) -> bool:
    return len(messages) > COMPACTION_THRESHOLD


def get_messages_to_summarize(messages: list) -> list:
    return messages[:-RECENT_MESSAGES_TO_KEEP]


def get_recent_messages(messages: list) -> list:
    return messages[-RECENT_MESSAGES_TO_KEEP:]


def get_latest_human_message(messages: list[AnyMessage]) -> HumanMessage:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message

    raise ValueError("A human message is required.")
