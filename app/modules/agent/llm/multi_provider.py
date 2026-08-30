from typing import AsyncGenerator, List, Dict, Any, Optional
from app.modules.agent.llm.base import LLMProvider
from app.modules.agent.llm.openai_compatible import OpenAICompatibleProvider
from app.core.config import settings
from app.core.logging import logger

class ResilientMultiProvider(LLMProvider):
    """
    Multi-Provider LLM Switcher with automatic fallback.
    Sequentially cycles through configured providers (Groq, OpenRouter, TokenRouter)
    whenever a provider encounters a quota error, rate limit, timeout, or server failure.
    """

    def __init__(self, providers: Optional[List[OpenAICompatibleProvider]] = None):
        self.providers = providers or self._build_default_providers()
        self.last_active_provider: Optional[OpenAICompatibleProvider] = self.providers[0] if self.providers else None

    @classmethod
    def from_settings(cls) -> "ResilientMultiProvider":
        return cls()

    def _build_default_providers(self) -> List[OpenAICompatibleProvider]:
        ordered_providers: List[OpenAICompatibleProvider] = []
        order = [p.strip().lower() for p in settings.LLM_PROVIDER_ORDER.split(",") if p.strip()]

        for p_name in order:
            if p_name == "groq" and settings.GROQ_API_KEY and settings.GROQ_API_KEY.strip():
                models_str = getattr(settings, "GROQ_MODELS", None) or settings.GROQ_MODEL or "llama-3.3-70b-versatile"
                models = [m.strip() for m in models_str.split(",") if m.strip()]
                for m in models:
                    ordered_providers.append(OpenAICompatibleProvider(
                        name="groq",
                        api_key=settings.GROQ_API_KEY,
                        base_url=settings.GROQ_BASE_URL or "https://api.groq.com/openai/v1",
                        model=m,
                        timeout=45.0,
                    ))
            elif p_name == "openrouter" and settings.OPENROUTER_API_KEY and settings.OPENROUTER_API_KEY.strip():
                models_str = getattr(settings, "OPENROUTER_MODELS", None) or settings.OPENROUTER_MODEL or "meta-llama/llama-3.3-70b-instruct:free"
                models = [m.strip() for m in models_str.split(",") if m.strip()]
                for m in models:
                    ordered_providers.append(OpenAICompatibleProvider(
                        name="openrouter",
                        api_key=settings.OPENROUTER_API_KEY,
                        base_url=settings.OPENROUTER_BASE_URL or "https://openrouter.ai/api/v1",
                        model=m,
                        timeout=60.0,
                    ))
            elif p_name == "tokenrouter" and settings.TOKENROUTER_API_KEY and settings.TOKENROUTER_API_KEY.strip():
                models_str = getattr(settings, "TOKENROUTER_MODELS", None) or settings.TOKENROUTER_MODEL or "z-ai/glm-5.3-free"
                models = [m.strip() for m in models_str.split(",") if m.strip()]
                for m in models:
                    ordered_providers.append(OpenAICompatibleProvider(
                        name="tokenrouter",
                        api_key=settings.TOKENROUTER_API_KEY,
                        base_url=settings.TOKENROUTER_BASE_URL or "https://api.tokenrouter.com/v1",
                        model=m,
                        timeout=60.0,
                    ))

        # If none have API keys, instantiate configured fallback stubs
        if not ordered_providers:
            ordered_providers = [
                OpenAICompatibleProvider("groq", settings.GROQ_API_KEY, settings.GROQ_BASE_URL, settings.GROQ_MODEL),
                OpenAICompatibleProvider("openrouter", settings.OPENROUTER_API_KEY, settings.OPENROUTER_BASE_URL, settings.OPENROUTER_MODEL),
                OpenAICompatibleProvider("tokenrouter", settings.TOKENROUTER_API_KEY, settings.TOKENROUTER_BASE_URL, settings.TOKENROUTER_MODEL),
            ]

        return ordered_providers

    @property
    def provider_name(self) -> str:
        return self.last_active_provider.provider_name if self.last_active_provider else "multi-provider"

    @property
    def model_name(self) -> str:
        return self.last_active_provider.model_name if self.last_active_provider else "auto"

    @property
    def model_tag(self) -> str:
        return self.last_active_provider.model_tag if self.last_active_provider else "multi-provider"

    async def chat_complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        errors = []

        configured = [p for p in self.providers if p.is_configured()]
        if not configured:
            configured = self.providers

        for provider in configured:
            try:
                res = await provider.chat_complete(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self.last_active_provider = provider
                return res
            except Exception as e:
                err_str = str(e)
                errors.append(f"{provider.name} ({err_str})")
                logger.warning(f"⚠️ Provider '{provider.name}' failed: {err_str}. Switching to next provider in fallback chain...")

        # If all failed
        full_err = " | ".join(errors)
        raise RuntimeError(f"All configured LLM providers failed: {full_err}")

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        configured = [p for p in self.providers if p.is_configured()]
        if not configured:
            configured = self.providers

        errors = []
        for provider in configured:
            try:
                self.last_active_provider = provider
                has_yielded = False
                async for chunk in provider.stream_chat(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    if "error" in chunk:
                        raise RuntimeError(chunk["error"])
                    has_yielded = True
                    yield chunk
                return
            except Exception as e:
                errors.append(f"{provider.name} ({str(e)})")
                logger.warning(f"⚠️ Stream failed on provider '{provider.name}': {e}. Attempting fallback...")

        yield {"error": f"All LLM streaming providers failed: {' | '.join(errors)}"}
