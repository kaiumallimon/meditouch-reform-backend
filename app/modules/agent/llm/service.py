from typing import Optional
from app.modules.agent.llm.base import LLMProvider
from app.modules.agent.llm.multi_provider import ResilientMultiProvider

class LLMService:
    """Manages the lifecycle of LLM providers with automatic fallback."""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or ResilientMultiProvider.from_settings()

    def get_provider(self) -> LLMProvider:
        return self.provider
