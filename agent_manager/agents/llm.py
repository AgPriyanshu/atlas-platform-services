from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from pydantic import SecretStr


@dataclass
class LLMConfig:
    model: str
    base_url: str
    api_key: SecretStr
    timeout: float
    temperature: float


class LLMFactory:
    @staticmethod
    def create_llm(config: LLMConfig):
        return ChatOpenAI(
            model=config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
            temperature=config.temperature,
        )
