"""Anthropic Claude analyzer.

The model receives the vacancy and the candidate resume/profile and returns a
strict JSON verdict. It is instructed to use ONLY facts from the resume — it
must never invent experience, skills or achievements.
"""
from __future__ import annotations

import json

from ..config import Settings
from .base import AIProvider, AnalysisContext, AnalysisResult

SYSTEM_PROMPT = (
    "You are a strict recruitment-matching assistant. Compare a vacancy against "
    "a candidate's resume and profile and decide how well it fits. Use ONLY "
    "facts explicitly present in the resume/profile — never invent experience, "
    "skills, employers or achievements. Respond with a single JSON object and "
    "nothing else, using this schema: {\"score\": int 0-100, "
    "\"experience_match\": int 0-100, \"skills_match\": int 0-100, "
    "\"title_match\": int 0-100, \"salary_match\": int 0-100, "
    "\"format_match\": int 0-100, \"reasons\": [string], \"risks\": [string]}. "
    "Reasons and risks must be short and in the language of the vacancy."
)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.s = settings
        # Imported lazily so the package is optional when using the mock provider.
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _user_prompt(self, ctx: AnalysisContext) -> str:
        salary = "не указана"
        if ctx.salary_from or ctx.salary_to:
            salary = f"{ctx.salary_from or ''}–{ctx.salary_to or ''}"
        return json.dumps(
            {
                "vacancy": {
                    "title": ctx.title,
                    "company": ctx.company,
                    "area": ctx.area,
                    "salary": salary,
                    "schedule": ctx.schedule,
                    "experience": ctx.experience,
                    "employment": ctx.employment,
                    "description": ctx.description[:6000],
                },
                "candidate": {
                    "resume": ctx.resume_text[:6000],
                    "target_titles": ctx.target_titles,
                    "alt_titles": ctx.alt_titles,
                    "skills": ctx.skills,
                    "remote_ok": ctx.remote_ok,
                    "min_salary": ctx.min_salary,
                    "stop_words": ctx.stop_words,
                },
            },
            ensure_ascii=False,
        )

    def analyze(self, ctx: AnalysisContext) -> AnalysisResult:
        msg = self._client.messages.create(
            model=self.s.ai_model,
            max_tokens=self.s.ai_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self._user_prompt(ctx)}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        ).strip()
        data = _extract_json(text)
        return AnalysisResult.validate(data, provider=self.name)

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._client.messages.create(
                model=self.s.ai_model,
                max_tokens=16,
                messages=[{"role": "user", "content": "ping — reply with 'ok'"}],
            )
            return True, "anthropic reachable"
        except Exception as exc:  # noqa: BLE001
            return False, f"anthropic error: {exc}"


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in AI response: {text[:200]}")
    return json.loads(text[start : end + 1])
