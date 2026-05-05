from __future__ import annotations

from .. import config
from .anthropic_provider import AnthropicProvider
from .base import TranslationProvider
from .glm_provider import GlmProvider
from .openai_provider import OpenAIProvider


def build_provider(name: str | None = None) -> TranslationProvider:
    cfg = config.load()
    chosen = (name or cfg.translation_provider).lower()
    model = cfg.model_for(chosen)
    api_key = cfg.api_key_for(chosen)
    if chosen == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if chosen == "openai":
        return OpenAIProvider(api_key=api_key, model=model)
    if chosen == "glm":
        return GlmProvider(api_key=api_key, model=model)
    raise ValueError(f"Unknown provider: {chosen}")


def build_metadata_provider() -> TranslationProvider:
    cfg = config.load()
    chosen = cfg.metadata_provider
    model = cfg.metadata_model or cfg.model_for(chosen)
    api_key = cfg.api_key_for(chosen)
    if chosen == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if chosen == "openai":
        return OpenAIProvider(api_key=api_key, model=model)
    if chosen == "glm":
        return GlmProvider(api_key=api_key, model=model)
    raise ValueError(f"Unknown provider: {chosen}")


__all__ = [
    "TranslationProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "GlmProvider",
    "build_provider",
    "build_metadata_provider",
]
