from __future__ import annotations

from abc import ABC, abstractmethod

TRANSLATION_SYSTEM_PROMPT = (
    "You are a professional Japanese translator specializing in academic papers in "
    "computer science, mathematics, and related fields. Translate the user's English "
    "text into natural, technical Japanese suitable for a Japanese researcher reader. "
    "Rules:\n"
    "- Preserve all Markdown structure (headings, lists, code blocks, tables).\n"
    "- Preserve LaTeX math exactly (`$...$`, `$$...$$`, `\\(...\\)`, `\\[...\\]`).\n"
    "- Keep inline citations like `[12]` or `(Smith et al., 2020)` unchanged.\n"
    "- For technical terms, give the standard Japanese term followed by the English "
    "in parentheses on first occurrence within a section, "
    "e.g. 「強化学習(Reinforcement Learning)」.\n"
    "- Do not add commentary, do not summarize, do not skip content. Output Japanese "
    "translation only.\n"
    "- If the input contains a figure/table caption, translate it; if it contains "
    "placeholder text like `[Figure 3]`, leave the placeholder.\n\n"
    "Previously translated context (use for terminology consistency, do not repeat): "
    "{context}"
)

METADATA_SYSTEM_PROMPT = (
    "You extract bibliographic metadata from the opening pages of an academic paper. "
    "Respond with ONLY a JSON object, no commentary, with keys: "
    "`title` (string), `authors` (array of strings, in order, given names first), "
    "`publication_date` (ISO 8601 `YYYY-MM-DD`, or `YYYY-MM`, or `YYYY` — whichever "
    "is most precisely supported by the text; null if unknown), "
    "`abstract` (string; empty if not present). "
    "If a field cannot be confidently determined, use null (or `[]` for authors). "
    "Do not invent."
)

REQUEST_TIMEOUT_SECONDS = 60.0


class TranslationProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def translate_chunk(self, text: str, *, context: str = "") -> str:
        """Translate a single chunk of English academic text to Japanese."""

    @abstractmethod
    async def complete_json(self, system: str, user: str) -> str:
        """Run a one-shot JSON-returning completion (used for metadata extraction).

        Returns the raw text response; the caller must json.loads it.
        """
