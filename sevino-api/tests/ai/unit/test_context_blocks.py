"""Unit tests for ``app.ai.context_blocks`` (SEV-615).

Context attachments are persisted in ``messages.content_blocks`` but are never
streamed and never replayed. Each ``ContextKind`` has a subclass that owns its
short ``render_hint`` describing the open screen (``kind``-only; ``data`` never
reaches the model).
"""

import pytest
from pydantic import ValidationError

from app.ai.context_blocks import (
    ContextBlock,
    ContextBlockAdapter,
    FundingContextBlock,
    HoldingsContextBlock,
    PortfolioContextBlock,
    RadarContextBlock,
    build_context_block,
)
from app.ai.context_blocks.base import _DEFAULT_HINT
from app.schemas.conversations import ContextKind


class TestBuildContextBlockDispatch:
    @pytest.mark.parametrize(
        ("kind", "cls"),
        [
            (ContextKind.PORTFOLIO, PortfolioContextBlock),
            (ContextKind.HOLDINGS, HoldingsContextBlock),
            (ContextKind.FUNDING, FundingContextBlock),
            (ContextKind.RADAR, RadarContextBlock),
        ],
    )
    def test_dispatches_to_subclass_by_kind(self, kind, cls):
        block = build_context_block(block_id="01A", kind=kind, data={})
        assert isinstance(block, cls)
        assert isinstance(block, ContextBlock)

    def test_every_kind_has_a_subclass(self):
        # Completeness guard: adding a ``ContextKind`` member without a
        # subclass makes the discriminated union fail to construct it.
        for kind in ContextKind:
            assert isinstance(
                build_context_block(block_id="b", kind=kind, data={}),
                ContextBlock,
            )

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            ContextBlockAdapter.validate_python(
                {"block_id": "b", "kind": "bogus", "data": {}}
            )

    def test_persisted_dump_shape_is_stable(self):
        # iOS resume + persistence depend on this exact JSONB shape; ``kind``
        # is the plain wire string, not the enum repr.
        dump = build_context_block(
            block_id="01J", kind=ContextKind.FUNDING, data={"apy": "0.04"}
        ).model_dump(mode="json")
        assert dump == {
            "type": "context",
            "block_id": "01J",
            "kind": "funding",
            "data": {"apy": "0.04"},
        }


class TestRenderHint:
    _HINTS = {
        ContextKind.PORTFOLIO: (
            "The user is currently viewing their portfolio. This screen "
            "shows their total account value, the gain or loss over a "
            "selected time range, and an interactive value-over-time chart "
            "with range options from one day to all-time. Their message may "
            "be referring to a figure, trend, or time period shown here."
        ),
        ContextKind.HOLDINGS: (
            "The user is currently viewing their holdings: the list of "
            "positions they own, each showing its ticker, share count, "
            "market value, and unrealized gain or loss, alongside an "
            "uninvested-cash row. Tapping a position reveals its day's gain, "
            "total gain, and average cost. Their message may be referring to "
            "one of these positions or its details."
        ),
        ContextKind.FUNDING: (
            "The user is currently viewing their cash / funding screen. This "
            "screen shows their uninvested cash balance and the interest "
            "(APY) it earns, interest earned this month and over its "
            "lifetime, buying power, pending deposits, the FDIC-insured "
            "limit, and controls to deposit, withdraw, or link a bank. Their "
            "message may be referring to their cash, yield, or a transfer "
            "shown here."
        ),
        ContextKind.RADAR: (
            "The user is currently viewing their radar watchlist: a list of "
            "tickers Sevino is surfacing, each with a short headline, its "
            "current price and percent change, and when the item expires, "
            "any of which they can star. Their message may be referring to "
            "one of these tickers or headlines."
        ),
    }

    def test_each_kind_renders_a_kind_only_hint_without_data(self):
        # ``data`` is opaque and must never reach the model — every kind's
        # hint is a ``kind``-only sentence regardless of what it carries.
        for kind, expected in self._HINTS.items():
            block = build_context_block(
                block_id="b",
                kind=kind,
                data={"equity": "12500.50", "secret": "leak?"},
            )
            hint = block.render_hint()
            assert hint == expected
            assert "12500.50" not in hint
            assert "secret" not in hint
        assert set(self._HINTS) == set(ContextKind)  # every kind covered

    def test_base_class_falls_back_to_default_hint(self):
        # The base is never constructed in production (always via a subclass),
        # but its default keeps an unmapped kind from leaking nothing.
        base = ContextBlock(block_id="b", kind=ContextKind.PORTFOLIO, data={})
        assert base.render_hint() == _DEFAULT_HINT
