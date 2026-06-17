from typing import AsyncGenerator

from .schemas import GlobalMessageState, Node, UIAction


class Agent:
    def __init__(self, graph):
        self.graph = graph

    async def astream(
        self, input: GlobalMessageState, config
    ) -> AsyncGenerator[tuple[str, UIAction | None], None]:
        content_streamed = False
        pending_ui_action = None

        async for mode, data in self.graph.astream(
            input, config=config, stream_mode=["messages", "updates"]
        ):
            if mode == "updates":
                for node_name, node_output in data.items():
                    if not isinstance(node_output, dict):
                        continue

                    if node_name == Node.UI_EXPERT:
                        pending_ui_action = node_output.get("ui_action")
                        continue

                    if node_name == Node.RESPONDER:
                        final_response = node_output.get("final_response")

                        if final_response and not content_streamed:
                            yield final_response, pending_ui_action

                continue

            chunk, metadata = data

            if metadata.get("langgraph_node") != Node.RESPONDER:
                continue

            chunk_content = chunk.content if hasattr(chunk, "content") else None

            if not chunk_content:
                continue

            if not isinstance(chunk_content, str):
                chunk_content = str(chunk_content)

            content_streamed = True
            yield chunk_content, None
