"""Anthropic model identifiers.

``MAIN`` is env-overridable via ``ANTHROPIC_MODEL_MAIN``. ``SMOKE`` is the
cheap fixed model used by CI.
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
    return ModelConfig(model_id=MODELS.MAIN)
