"""AI analysis providers."""
from __future__ import annotations

from ..config import Settings
from .base import AIProvider, AnalysisResult
from .mock import MockAIProvider


def build_ai(settings: Settings) -> AIProvider:
    if settings.ai_provider == "anthropic" and settings.anthropic_api_key:
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    return MockAIProvider(settings)


__all__ = ["AIProvider", "AnalysisResult", "MockAIProvider", "build_ai"]
