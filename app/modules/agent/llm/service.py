from typing import Optional
from app.modules.agent.llm.base import LLMProvider
from app.modules.agent.llm.tokenrouter import TokenRouterProvider
from app.core.config import settings

class LLMService:
    """Manages the lifecycle of LLM providers with dependency injection."""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider or TokenRouterProvider(
            api_key=settings.TOKENROUTER_API_KEY,
            base_url=settings.TOKENROUTER_BASE_URL,
            model=settings.TOKENROUTER_MODEL,
        )

    def get_provider(self) -> LLMProvider:
        return self.provider
