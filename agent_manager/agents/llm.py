from dataclasses import dataclass
from typing import Optional

import httpx
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


@dataclass
class LLMConfig:
    model: str
    base_url: str
    api_key: SecretStr
    timeout: float
    temperature: Optional[float] = None


class LLMFactory:
    @staticmethod
    def create_llm(config: LLMConfig):
        http_client = httpx.Client(trust_env=False)
        async_http_client = httpx.AsyncClient(trust_env=False)

        return ChatOpenAI(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
            temperature=config.temperature,
            http_client=http_client,
            http_async_client=async_http_client,
        )
