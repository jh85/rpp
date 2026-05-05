from __future__ import annotations

import asyncio

import anthropic

from .base import (
    REQUEST_TIMEOUT_SECONDS,
    TRANSLATION_SYSTEM_PROMPT,
    TranslationProvider,
)


class AnthropicProvider(TranslationProvider):
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS
        )

    async def translate_chunk(self, text: str, *, context: str = "") -> str:
        system = TRANSLATION_SYSTEM_PROMPT.format(context=context or "(none)")
        return await _with_retry(
            lambda: self._call(system=system, user=text, max_tokens=8192)
        )

    async def complete_json(self, system: str, user: str) -> str:
        return await _with_retry(
            lambda: self._call(system=system, user=user, max_tokens=2048)
        )

    async def _call(self, *, system: str, user: str, max_tokens: int) -> str:
        msg = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()


async def _with_retry(fn):  # type: ignore[no-untyped-def]
    try:
        return await fn()
    except (
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.RateLimitError,
    ):
        await asyncio.sleep(2.0)
        return await fn()
