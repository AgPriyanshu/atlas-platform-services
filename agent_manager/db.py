from contextlib import asynccontextmanager

from django.conf import settings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def _build_conn_string() -> str:
    db = settings.DATABASES["default"]

    return (
        f"postgresql://{db['USER']}:{db['PASSWORD']}"
        f"@{db['HOST']}:{db['PORT']}/{db['NAME']}"
    )


@asynccontextmanager
async def get_postgres_checkpointer():
    async with AsyncPostgresSaver.from_conn_string(_build_conn_string()) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
