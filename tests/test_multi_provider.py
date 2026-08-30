import pytest
from unittest.mock import AsyncMock, patch
from app.modules.agent.llm.base import LLMProvider
from app.modules.agent.llm.openai_compatible import OpenAICompatibleProvider
from app.modules.agent.llm.multi_provider import ResilientMultiProvider

@pytest.mark.asyncio
async def test_resilient_multi_provider_fallback_on_403_quota_error():
    p1 = OpenAICompatibleProvider(
        name="tokenrouter",
        api_key="sk-tokenrouter-fail",
        base_url="https://api.tokenrouter.com/v1",
        model="z-ai/glm-5.3-free",
    )
    
    p2 = OpenAICompatibleProvider(
        name="groq",
        api_key="gsk-groq-valid",
        base_url="https://api.groq.com/openai/v1",
        model="llama-3.3-70b-versatile",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        # First call to TokenRouter returns 403 Insufficient Quota
        mock_resp_fail = AsyncMock()
        mock_resp_fail.status_code = 403
        mock_resp_fail.text = '{"error":{"message":"User credit limit is insufficient","code":"insufficient_user_quota"}}'

        # Second call to Groq returns 200 OK
        mock_resp_success = AsyncMock()
        mock_resp_success.status_code = 200
        mock_resp_success.json = lambda: {
            "choices": [{"message": {"role": "assistant", "content": "Hello from Groq Llama 3.3!"}}]
        }

        mock_post.side_effect = [mock_resp_fail, mock_resp_success]

        multi = ResilientMultiProvider(providers=[p1, p2])
        res = await multi.chat_complete(messages=[{"role": "user", "content": "Hi"}])

        assert res is not None
        assert res["_provider"] == "groq"
        assert res["_model"] == "llama-3.3-70b-versatile"
        assert res["_tag"] == "groq / llama-3.3-70b-versatile"
        assert res["choices"][0]["message"]["content"] == "Hello from Groq Llama 3.3!"
        assert multi.last_active_provider.name == "groq"

@pytest.mark.asyncio
async def test_resilient_multi_provider_all_fail_raises_runtime_error():
    p1 = OpenAICompatibleProvider(name="groq", api_key="k1", base_url="https://api.groq.com/openai/v1", model="m1")
    p2 = OpenAICompatibleProvider(name="openrouter", api_key="k2", base_url="https://openrouter.ai/api/v1", model="m2")

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        multi = ResilientMultiProvider(providers=[p1, p2])
        with pytest.raises(RuntimeError) as exc_info:
            await multi.chat_complete(messages=[{"role": "user", "content": "Hi"}])

        assert "All configured LLM providers failed" in str(exc_info.value)
