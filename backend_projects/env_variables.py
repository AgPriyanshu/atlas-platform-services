import os
from enum import Enum


class EnvVariable(Enum):
    ENV = os.environ.get("ENV", "production")
    DEBUG = os.environ["DEBUG"]
    DB_NAME = os.environ["DB_NAME"]
    DB_USER = os.environ["DB_USER"]
    DB_PASSWORD = os.environ["DB_PASSWORD"]
    DB_HOST = os.environ["DB_HOST"]
    DB_PORT = os.environ["DB_PORT"]

    INFRA_PROVIDER = os.environ.get("INFRA_PROVIDER", "k8s")

    REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
    REDIS_PORT = os.environ.get("REDIS_PORT", "6379")

    S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:8333")
    S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
    S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")
    S3_REGION = os.environ.get("S3_REGION", "ap-south-1")
    S3_BUCKET_NAME = os.environ.get(
        "S3_BUCKET_NAME", os.environ.get("S3_BUCKET", "woa")
    )
    S3_BUCKET = os.environ.get("S3_BUCKET", S3_BUCKET_NAME)

    LLM_BASE_URL = os.environ.get("LLM_SERVER_URL", "http://100.64.122.97:8080/v1")
    LLM_DEFAULT_MODEL = os.environ.get("LLM_DEFAULT_MODEL", "Qwen/Qwen3-8B-AWQ")
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
    LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2000"))
    LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", 0.7))
    LLM_ENABLE_TOOLS = os.environ.get("LLM_ENABLE_TOOLS", "true").lower() == "true"

    LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "")
