"""Post-schema safety checks in `validate_pick`: no hallucinated symbols,
bucket tags must match the pool."""

from app.services.radar_job.candidate_sourcer import Candidate
from app.services.radar_job.llm import RadarPick, validate_pick


def _pool() -> dict[str, Candidate]:
    candidates = [
        Candidate(symbol="AAPL", name="Apple", sector="Technology", market_cap=1, bucket="owned_sector"),
        Candidate(symbol="XOM", name="Exxon", sector="Energy", market_cap=1, bucket="diversification"),
    ]
    return {c.symbol.upper(): c for c in candidates}


def _pick(symbol="AAPL", label="A mature large-cap", bucket="owned_sector", relevance=0.7):
    return RadarPick(symbol=symbol, label=label, bucket=bucket, relevance=relevance)


def test_pick_in_pool_with_matching_bucket_passes():
    assert validate_pick(_pick(), _pool()) == []


def test_symbol_not_in_pool_rejected():
    issues = validate_pick(_pick(symbol="TSLA"), _pool())
    assert any("not in candidate pool" in i for i in issues)


def test_symbol_match_is_case_insensitive():
    assert validate_pick(_pick(symbol="aapl"), _pool()) == []


def test_bucket_mismatch_rejected():
    issues = validate_pick(_pick(symbol="XOM", bucket="owned_sector"), _pool())
    assert any("bucket should be diversification" in i for i in issues)


def test_prescriptive_label_rejected():
    issues = validate_pick(_pick(label="You should buy this"), _pool())
    assert any("prescriptive" in i for i in issues)


def test_multiple_problems_collected():
    issues = validate_pick(
        _pick(symbol="NVDA", label="A great buy", bucket="owned_sector"), _pool()
    )
    assert len(issues) == 2  # prescriptive + not in pool
