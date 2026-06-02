from .schemas import Node


def create_path_map(nodes: list[Node | str]) -> dict:
    return {node: node for node in nodes}
