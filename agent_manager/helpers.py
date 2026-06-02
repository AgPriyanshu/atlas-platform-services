import json

from .schemas import IncomingMessage


def parse_incoming_message(text: str) -> IncomingMessage:
    parsed_text = json.loads(text)

    return IncomingMessage(
        message=parsed_text.get("message"), context=parsed_text.get("context")
    )
