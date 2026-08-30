import json
import httpx
from typing import AsyncGenerator, List, Dict, Any, Optional
from app.modules.agent.llm.base import LLMProvider
from app.core.logging import logger

class OpenAICompatibleProvider(LLMProvider):
    """
    Generic OpenAI-compatible provider supporting Groq, OpenRouter, TokenRouter, etc.
    """

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
    ):
        self.name = name
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in self.base_url:
            self.headers["HTTP-Referer"] = "https://meditouch.health"
            self.headers["X-Title"] = "MediTouch AI"

    @property
    def provider_name(self) -> str:
        return self.name

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def model_tag(self) -> str:
        return f"{self.name} / {self.model}"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key != "")

    async def chat_complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        if not self.is_configured():
            raise ValueError(f"API key for provider '{self.name}' is not configured.")

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

        timeout_config = httpx.Timeout(self.timeout, connect=15.0, read=self.timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout_config) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    error_body = resp.text
                    logger.warning(f"[{self.name}] API error ({resp.status_code}): {error_body}")
                    raise RuntimeError(f"[{self.name}] HTTP {resp.status_code}: {error_body}")
                
                data = resp.json()
                data["_provider"] = self.name
                data["_model"] = self.model
                data["_tag"] = self.model_tag
                return data
        except httpx.TimeoutException:
            logger.warning(f"[{self.name}] Request timed out after {self.timeout}s")
            raise RuntimeError(f"[{self.name}] Request timed out after {self.timeout}s")
        except httpx.ConnectError as e:
            logger.warning(f"[{self.name}] Connection failed to {self.base_url}: {e}")
            raise RuntimeError(f"[{self.name}] Cannot connect to {self.base_url}: {e}")

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.is_configured():
            raise ValueError(f"API key for provider '{self.name}' is not configured.")

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

        timeout_config = httpx.Timeout(self.timeout, connect=15.0, read=self.timeout)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    err_msg = error_text.decode("utf-8", errors="ignore")
                    logger.warning(f"[{self.name}] Stream Error ({response.status_code}): {err_msg}")
                    yield {"error": f"[{self.name}] error ({response.status_code}): {err_msg}", "_provider": self.name, "_model": self.model, "_tag": self.model_tag}
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield {"finish_reason": "stop", "_provider": self.name, "_model": self.model, "_tag": self.model_tag}
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
                            "_provider": self.name,
                            "_model": self.model,
                            "_tag": self.model_tag,
                        }
                    except json.JSONDecodeError:
                        continue
