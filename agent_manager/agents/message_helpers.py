from langchain.messages import AnyMessage, HumanMessage

from .constants import MAX_CONTEXT_MESSAGES


def trim_messages(messages: list, trim_amount: int = MAX_CONTEXT_MESSAGES) -> list:
    return messages[-trim_amount:]


def get_latest_human_message(messages: list[AnyMessage]) -> HumanMessage:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message

    raise ValueError("A human message is required.")
