"""Pydantic schema acceptance for RadarLLM output.

Starts from a valid 5-pick batch and flips one constraint at a time, so a
raised ValidationError isolates exactly one rule.
"""

import pytest
from pydantic import ValidationError

from app.services.radar_job.llm import RadarLLMOutput, RadarPick


def _pick(symbol="AAPL", label="A mature large-cap in tech", bucket="owned_sector", relevance=0.8):
    return {"symbol": symbol, "label": label, "bucket": bucket, "relevance": relevance}


def _picks(n: int) -> list[dict]:
    return [_pick(symbol=f"SYM{i}") for i in range(n)]


def test_valid_batch_parses():
    out = RadarLLMOutput.model_validate({"picks": _picks(5)})
    assert len(out.picks) == 5
    assert isinstance(out.picks[0], RadarPick)


def test_seven_picks_is_the_upper_bound():
    out = RadarLLMOutput.model_validate({"picks": _picks(7)})
    assert len(out.picks) == 7


def test_too_few_picks_rejected():
    with pytest.raises(ValidationError):
        RadarLLMOutput.model_validate({"picks": _picks(4)})


def test_too_many_picks_rejected():
    with pytest.raises(ValidationError):
        RadarLLMOutput.model_validate({"picks": _picks(8)})


def test_label_over_120_chars_rejected():
    picks = _picks(5)
    picks[0]["label"] = "x" * 121
    with pytest.raises(ValidationError):
        RadarLLMOutput.model_validate({"picks": picks})


def test_label_at_120_chars_allowed():
    picks = _picks(5)
    picks[0]["label"] = "x" * 120
    out = RadarLLMOutput.model_validate({"picks": picks})
    assert len(out.picks[0].label) == 120


@pytest.mark.parametrize("relevance", [-0.1, 1.1, 2.0])
def test_relevance_out_of_range_rejected(relevance):
    picks = _picks(5)
    picks[0]["relevance"] = relevance
    with pytest.raises(ValidationError):
        RadarLLMOutput.model_validate({"picks": picks})


def test_unknown_bucket_rejected():
    picks = _picks(5)
    picks[0]["bucket"] = "speculative"
    with pytest.raises(ValidationError):
        RadarLLMOutput.model_validate({"picks": picks})
