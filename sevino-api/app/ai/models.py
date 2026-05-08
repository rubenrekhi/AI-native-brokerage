"""Anthropic model identifiers used by the AI agent.

Per AI v0 plan D9 (sevino-api/docs/ai-v0-plan.md):
- ``MAIN`` is the default model for the main agent. Env-overridable via
  ``ANTHROPIC_MODEL_MAIN`` so we can A/B in prod without redeploy.
- ``SMOKE`` is the cheap model used by the CI smoke harness (fixed).
"""
from dataclasses import dataclass

from app.ai.runtime.types import ModelConfig
from app.config import settings


@dataclass(frozen=True)
class _Models:
    MAIN: str
    SMOKE: str


MODELS = _Models(
    MAIN=settings.anthropic_model_main,
    SMOKE="claude-haiku-4-5-20251001",
)


def get_default_model_config() -> ModelConfig:
    """FastAPI dependency that returns the default per-turn model config.

    Production resolves to ``MODELS.MAIN``. Tests override via
    ``app.dependency_overrides[get_default_model_config]`` — the smoke
    harness installs ``ModelConfig(model_id=MODELS.SMOKE)`` so real
    Anthropic calls bill at the cheap Haiku tier.
    """
    return ModelConfig(model_id=MODELS.MAIN)
