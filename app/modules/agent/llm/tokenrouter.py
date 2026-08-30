from app.modules.agent.llm.openai_compatible import OpenAICompatibleProvider

class TokenRouterProvider(OpenAICompatibleProvider):
    """Backwards-compatible alias for TokenRouter."""
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        from app.core.config import settings
        super().__init__(
            name="tokenrouter",
            api_key=api_key or settings.TOKENROUTER_API_KEY,
            base_url=base_url or settings.TOKENROUTER_BASE_URL,
            model=model or settings.TOKENROUTER_MODEL,
        )
