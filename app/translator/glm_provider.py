from __future__ import annotations

import asyncio

from zhipuai import ZhipuAI

from .base import (
    REQUEST_TIMEOUT_SECONDS,
    TRANSLATION_SYSTEM_PROMPT,
    TranslationProvider,
)


class GlmProvider(TranslationProvider):
    """ZhipuAI GLM provider.

    The official `zhipuai` SDK is synchronous, so we run calls in a thread.
    """

    name = "glm"

    def __init__(self, *, api_key: str, model: str) -> None:
        self.model = model
        self._client = ZhipuAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)

    async def translate_chunk(self, text: str, *, context: str = "") -> str:
        system = TRANSLATION_SYSTEM_PROMPT.format(context=context or "(none)")
        return await _with_retry(lambda: self._call(system, text))

    async def complete_json(self, system: str, user: str) -> str:
        return await _with_retry(lambda: self._call(system, user))

    async def _call(self, system: str, user: str) -> str:
        def _sync() -> str:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return (resp.choices[0].message.content or "").strip()

        return await asyncio.to_thread(_sync)


async def _with_retry(fn):  # type: ignore[no-untyped-def]
    try:
        return await fn()
    except Exception:
        await asyncio.sleep(2.0)
        return await fn()
