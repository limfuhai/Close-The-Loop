# api_client.py
import os
import json
import asyncio
import aiohttp
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator

moonshot_api_key = ""
deepseek_api_key = ""

# ── Model chain: tried in order. If one fails, the next one is used. ──────────
# To add or retire a model, edit this list only.
MODEL_CHAIN = [
    {"name": "DeepSeek Flash", "base_url": "https://api.deepseek.com",
     "model": "deepseek-flash", "api_key": deepseek_api_key},
    {"name": "Kimi K2.7 Code", "base_url": "https://api.moonshot.ai/v1",
     "model": "kimi-k2.7-code", "api_key": moonshot_api_key},
    {"name": "Kimi K2.6", "base_url": "https://api.moonshot.ai/v1",
     "model": "kimi-k2.6", "api_key": moonshot_api_key},
]
 
RATE_LIMIT_WAIT_SECONDS = 2
 
class ClaudeAPIClient:
    """Model client with failover across MODEL_CHAIN. Name kept for compatibility."""
 
    def __init__(self, api_key: Optional[str] = None):
        self.logger = logging.getLogger(__name__)
        # Only use models whose key is actually set
        self.chain = [m for m in MODEL_CHAIN if m["api_key"]]
        if not self.chain:
            raise ValueError(
                "No model API keys found. Set DEEPSEEK_API_KEY and/or MOONSHOT_API_KEY.")
        self.logger.info(f"Model chain: {[m['name'] for m in self.chain]}")
 
    def _build_messages(self, prompt, system_prompt=None, conversation_history=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": prompt})
        return messages
 
    async def _post(self, session, provider, payload):
        """One request to one provider. Retries once after a short wait on a rate limit (429)."""
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        body = {**payload, "model": provider["model"]}
        for attempt in range(2):
            async with session.post(
                f"{provider['base_url']}/chat/completions",
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as response:
                if response.status == 429 and attempt == 0:
                    self.logger.warning(f"{provider['name']} rate limited, retrying once")
                    await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
                    continue
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"{provider['name']} error ({response.status}): {error_text[:300]}")
                return await response.json()
 
    async def generate(self,
                       prompt: str,
                       max_tokens: int = 1024,
                       temperature: float = 0.7,
                       model: str = None,  # ignored: the chain decides the model
                       system_prompt: Optional[str] = None,
                       conversation_history: Optional[list[dict[str, str]]] = None) -> Dict[str, Any]:
        messages = self._build_messages(prompt, system_prompt, conversation_history)
        print(messages)
        payload = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
 
        errors = []
        async with aiohttp.ClientSession() as session:
            for provider in self.chain:
                try:
                    result = await self._post(session, provider, payload)
                    content = result["choices"][0]["message"]["content"]
                    if not content or not content.strip():
                        raise Exception(f"{provider['name']} returned an empty reply")
                    if provider is not self.chain[0]:
                        self.logger.warning(f"Served by fallback: {provider['name']}")
                    return {
                        "text": content,
                        "content": content,  # For backward compatibility
                        "usage": result.get("usage", {}),
                    }
                except Exception as e:
                    self.logger.error(f"{provider['name']} failed: {e}")
                    errors.append(str(e))
 
        raise Exception("All models failed: " + " | ".join(errors))
 
    async def _generate_stream(self, prompt: str,
                               max_tokens: int = 1024,
                               temperature: float = 0.7,
                               model: str = None,  # ignored: the chain decides the model
                               system_prompt: Optional[str] = None):
        """Stream a response. Fails over only before streaming starts."""
        messages = self._build_messages(prompt, system_prompt)
        payload = {"messages": messages, "max_tokens": max_tokens,
                   "temperature": temperature, "stream": True}
 
        errors = []
        async with aiohttp.ClientSession() as session:
            for provider in self.chain:
                headers = {
                    "Authorization": f"Bearer {provider['api_key']}",
                    "Content-Type": "application/json",
                }
                async with session.post(
                    f"{provider['base_url']}/chat/completions",
                    json={**payload, "model": provider["model"]},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"{provider['name']} stream failed: {error_text[:300]}")
                        errors.append(f"{provider['name']} ({response.status})")
                        continue  # nothing streamed yet, so try the next model
 
                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                if "choices" in data and len(data["choices"]) > 0:
                                    content = data["choices"][0].get("delta", {}).get("content", "")
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                continue
                    return
 
        raise Exception("All models failed to stream: " + " | ".join(errors))