from __future__ import annotations

import asyncio

import openai

from .base import (
    REQUEST_TIMEOUT_SECONDS,
    TRANSLATION_SYSTEM_PROMPT,
    TranslationProvider,
)


class OpenAIProvider(TranslationProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str) -> None:
        self.model = model
        self._client = openai.AsyncOpenAI(
            api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def translate_chunk(self, text: str, *, context: str = "") -> str:
        system = TRANSLATION_SYSTEM_PROMPT.format(context=context or "(none)")
        return await _with_retry(lambda: self._call(system, text, json_mode=False))

    async def complete_json(self, system: str, user: str) -> str:
        return await _with_retry(lambda: self._call(system, user, json_mode=True))

    async def _call(self, system: str, user: str, *, json_mode: bool) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


async def _with_retry(fn):  # type: ignore[no-untyped-def]
    try:
        return await fn()
    except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError):
        await asyncio.sleep(2.0)
        return await fn()
