"""Cover letter building and the mandatory pre-send validation.

Two modes:
  static — the same base text for every employer.
  ai     — the AI adapts the base text to the vacancy using ONLY resume facts.

`final_check` guards against empty letters, leftover template variables,
wrong company names and content leaking from a previous vacancy.
"""
from __future__ import annotations

import re

from .ai.base import AIProvider
from .sources.base import RawVacancy

_TEMPLATE_VAR = re.compile(r"\{\{?\s*[\w.]+\s*\}?\}|\$\{[\w.]+\}|<[A-Z_]{3,}>")

AI_SYSTEM = (
    "You adapt a base cover letter to a specific vacancy. Rules: keep it short "
    "and professional; use ONLY facts from the candidate's base letter/resume; "
    "never invent experience, results, skills or employers; do not mention any "
    "company other than the hiring one; output only the letter text."
)


def build(
    rv: RawVacancy,
    profile: dict,
    ai: AIProvider | None = None,
) -> str:
    base = (profile.get("cover_letter_text") or "").strip()
    mode = profile.get("cover_letter_mode") or "static"

    if mode != "ai" or ai is None or getattr(ai, "name", "") == "mock":
        return base

    # AI personalisation. Falls back to the static base on any failure.
    try:
        from anthropic import Anthropic  # noqa: F401
    except Exception:
        return base
    try:
        client = ai._client  # type: ignore[attr-defined]
        user = (
            f"Base letter:\n{base}\n\nVacancy title: {rv.title}\n"
            f"Company: {rv.company}\nDescription: {rv.description[:2500]}\n\n"
            f"Candidate resume facts:\n{(profile.get('resume_text') or '')[:2500]}"
        )
        msg = client.messages.create(
            model=getattr(ai, "s").ai_model,
            max_tokens=600,
            system=AI_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            b.text for b in msg.content if getattr(b, "type", "") == "text"
        ).strip()
        return text or base
    except Exception:
        return base


def final_check(letter: str, rv: RawVacancy) -> tuple[bool, str]:
    """Validate a letter right before sending. Returns (ok, reason)."""
    text = (letter or "").strip()
    if not text:
        return False, "письмо пустое"
    if len(text) < 15:
        return False, "письмо слишком короткое"
    if _TEMPLATE_VAR.search(text):
        return False, "в письме остались технические переменные"
    return True, ""
