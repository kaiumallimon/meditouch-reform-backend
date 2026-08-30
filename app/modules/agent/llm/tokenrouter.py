import json
import httpx
from typing import AsyncGenerator, List, Dict, Any, Optional
from app.modules.agent.llm.base import LLMProvider
from app.core.config import settings
from app.core.logging import logger

class TokenRouterProvider(LLMProvider):
    """
    OpenAI-compatible client for TokenRouter API.
    Streams deltas, tool_calls, and usage statistics.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.TOKENROUTER_API_KEY
        self.base_url = (base_url or settings.TOKENROUTER_BASE_URL).rstrip("/")
        self.model = model or settings.TOKENROUTER_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        if not self.api_key or self.api_key.strip() == "":
            raise ValueError(
                "TOKENROUTER_API_KEY is not configured. Please set your API key in backend/.env (e.g., TOKENROUTER_API_KEY=your_key)."
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        timeout_config = httpx.Timeout(120.0, connect=15.0, read=120.0)

        try:
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.error(f"TokenRouter API error [{resp.status_code}]: {resp.text}")
                    raise RuntimeError(f"TokenRouter API error ({resp.status_code}): {resp.text}")
                return resp.json()
        except httpx.TimeoutException:
            logger.error(f"Timeout waiting for TokenRouter response from {self.base_url}")
            raise RuntimeError(f"Request to LLM provider at '{self.base_url}' timed out (120s). The model may be under high load.")
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to LLM Provider at {self.base_url}: {e}")
            raise RuntimeError(
                f"Cannot connect to LLM provider at '{self.base_url}'. Please verify your TOKENROUTER_BASE_URL (or check internet connection). Details: {e}"
            )
        except httpx.RequestError as e:
            err_details = str(e) or type(e).__name__
            logger.error(f"Request error to {self.base_url}: {err_details}")
            raise RuntimeError(f"LLM request error to '{self.base_url}': {err_details}")

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        timeout_config = httpx.Timeout(120.0, connect=15.0, read=120.0)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    logger.error(f"TokenRouter Stream Error [{response.status_code}]: {error_text.decode('utf-8', errors='ignore')}")
                    yield {"error": f"TokenRouter error: {response.status_code}"}
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield {"finish_reason": "stop"}
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")

                        yield {
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    except json.JSONDecodeError:
                        continue
