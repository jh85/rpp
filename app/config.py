from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
PDF_DIR: Path = DATA_DIR / "pdfs"
TRANSLATION_DIR: Path = DATA_DIR / "translations"
DB_PATH: Path = DATA_DIR / "papers.db"

VALID_PROVIDERS = ("anthropic", "openai", "glm")


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    translation_provider: str
    metadata_provider: str
    anthropic_api_key: str
    anthropic_model: str
    openai_api_key: str
    openai_model: str
    zhipuai_api_key: str
    glm_model: str
    metadata_model: str
    translation_chunk_chars: int

    def model_for(self, provider: str) -> str:
        if provider == "anthropic":
            return self.anthropic_model
        if provider == "openai":
            return self.openai_model
        if provider == "glm":
            return self.glm_model
        raise ValueError(f"unknown provider: {provider}")

    def api_key_for(self, provider: str) -> str:
        if provider == "anthropic":
            return self.anthropic_api_key
        if provider == "openai":
            return self.openai_api_key
        if provider == "glm":
            return self.zhipuai_api_key
        raise ValueError(f"unknown provider: {provider}")


_cfg: Config | None = None


def load() -> Config:
    global _cfg
    if _cfg is not None:
        return _cfg

    load_dotenv(PROJECT_ROOT / ".env")

    translation_provider = os.getenv("TRANSLATION_PROVIDER", "anthropic").strip().lower()
    if translation_provider not in VALID_PROVIDERS:
        _die(f"TRANSLATION_PROVIDER must be one of {VALID_PROVIDERS}, got {translation_provider!r}")

    metadata_provider = os.getenv("METADATA_PROVIDER", "").strip().lower() or translation_provider
    if metadata_provider not in VALID_PROVIDERS:
        _die(f"METADATA_PROVIDER must be one of {VALID_PROVIDERS}, got {metadata_provider!r}")

    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4.1").strip()
    glm_model = os.getenv("GLM_MODEL", "glm-4-plus").strip()
    metadata_model = os.getenv("METADATA_MODEL", "").strip()

    cfg = Config(
        host=os.getenv("HOST", "127.0.0.1").strip(),
        port=int(os.getenv("PORT", "8765")),
        translation_provider=translation_provider,
        metadata_provider=metadata_provider,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=anthropic_model,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=openai_model,
        zhipuai_api_key=os.getenv("ZHIPUAI_API_KEY", "").strip(),
        glm_model=glm_model,
        metadata_model=metadata_model,
        translation_chunk_chars=int(os.getenv("TRANSLATION_CHUNK_CHARS", "12000")),
    )

    for provider in {cfg.translation_provider, cfg.metadata_provider}:
        if not cfg.api_key_for(provider):
            _die(
                f"Missing API key for provider {provider!r}. "
                f"Set the corresponding *_API_KEY in .env."
            )

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)

    _cfg = cfg
    return cfg


def _die(msg: str) -> None:
    print(f"[config] FATAL: {msg}", file=sys.stderr)
    sys.exit(1)
