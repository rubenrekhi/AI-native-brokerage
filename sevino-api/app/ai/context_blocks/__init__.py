"""Persisted context-attachment blocks, one subclass per ``ContextKind``.

Mirrors the ``Block`` discriminated-union pattern in ``app.ai.blocks``: the
``kind`` discriminator dispatches construction to the right subclass via
``ContextBlockAdapter``; no hand-written kind→class map. Unlike ``Block``
these are user attachments: input only, never streamed, never replayed
(SEV-615). Each subclass owns its short ``render_hint`` describing what its
screen shows. Modal kinds are ``kind``-driven (only a whitelisted, non-stale
field like the portfolio chart's range is projected from ``data``); the
``digest`` kind is the deliberate exception: its card is the subject of the
chat, so its hint folds in the full card content (a fixed snapshot, sent only
this turn, never replayed).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, TypeAdapter

from app.ai.context_blocks.base import ContextBlock
from app.ai.context_blocks.digest import DigestContextBlock
from app.ai.context_blocks.funding import FundingContextBlock
from app.ai.context_blocks.holdings import HoldingsContextBlock
from app.ai.context_blocks.portfolio import PortfolioContextBlock
from app.ai.context_blocks.radar import RadarContextBlock
from app.schemas.conversations import ContextKind

__all__ = [
    "ContextBlock",
    "ContextBlockAdapter",
    "DigestContextBlock",
    "FundingContextBlock",
    "HoldingsContextBlock",
    "PortfolioContextBlock",
    "RadarContextBlock",
    "build_context_block",
]

_ContextBlockUnion = (
    PortfolioContextBlock
    | HoldingsContextBlock
    | FundingContextBlock
    | RadarContextBlock
    | DigestContextBlock
)

ContextBlockAdapter: TypeAdapter[_ContextBlockUnion] = TypeAdapter(
    Annotated[_ContextBlockUnion, Field(discriminator="kind")]
)


def build_context_block(
    *, block_id: str, kind: ContextKind, data: dict[str, Any]
) -> ContextBlock:
    """Construct the ``ContextBlock`` subclass matching ``kind``.

    Dispatch is the discriminated union, so adding a kind is a new subclass,
    not another branch here.
    """
    return ContextBlockAdapter.validate_python(
        {"block_id": block_id, "kind": kind, "data": data}
    )
