from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any, Optional

class LLMProvider(ABC):
    """Abstract base class for all LLM inference providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g., 'groq', 'openrouter', 'tokenrouter')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier (e.g., 'llama-3.3-70b-versatile')."""
        pass

    @property
    def model_tag(self) -> str:
        """Formatted tag for UI attribution."""
        return f"{self.provider_name} / {self.model_name}"

    @abstractmethod
    async def chat_complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Performs a non-streaming chat completion."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streams response tokens and tool call chunks asynchronously."""
        pass
