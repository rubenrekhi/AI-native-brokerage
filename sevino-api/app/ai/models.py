"""Anthropic model identifiers used by the AI agent.

Per AI v0 plan D9 (sevino-api/docs/ai-v0-plan.md):
- ``MAIN`` is the default model for the main agent. Env-overridable via
  ``ANTHROPIC_MODEL_MAIN`` so we can A/B in prod without redeploy.
- ``SMOKE`` is the cheap model used by the CI smoke harness (fixed).
"""
from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class _Models:
    MAIN: str
    SMOKE: str


MODELS = _Models(
    MAIN=settings.anthropic_model_main,
    SMOKE="claude-haiku-4-5-20251001",
)
