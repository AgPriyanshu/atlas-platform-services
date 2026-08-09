from langfuse.langchain import CallbackHandler

from backend_projects.env_variables import EnvVariable

TRACE_NAME = "handle-chat-turn"
TRACE_TAGS = ["agent-manager"]


def is_tracing_enabled() -> bool:
    return bool(
        EnvVariable.LANGFUSE_PUBLIC_KEY.value and EnvVariable.LANGFUSE_SECRET_KEY.value
    )


def trace_config(session_id: str, user_id: str) -> dict:
    """Build the RunnableConfig fragment that sends one graph run to Langfuse.

    The handler is created per run so concurrent chat turns never share state.
    """
    if not is_tracing_enabled():
        return {}

    return {
        "run_name": TRACE_NAME,
        "callbacks": [CallbackHandler()],
        "metadata": {
            "langfuse_session_id": session_id,
            "langfuse_user_id": user_id,
            "langfuse_tags": TRACE_TAGS,
        },
    }
