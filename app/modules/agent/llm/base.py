from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any, Optional

class LLMProvider(ABC):
    """Abstract base class for all LLM inference providers."""

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
