from typing import Annotated

from pydantic import AfterValidator

# 50 states + DC + the US territories Alpaca's KYC `contact.state` accepts
# (AS, GU, MP, PR, VI, UM). Anything else — e.g. Canadian provinces like "ON" —
# is rejected by Alpaca with a 422, so we gate it at our own boundary instead.
US_STATE_CODES: frozenset[str] = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
        "AS", "GU", "MP", "PR", "VI", "UM",
    }
)


def _validate_us_state(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in US_STATE_CODES:
        raise ValueError("state must be a valid US state code")
    return normalized


USStateCode = Annotated[str, AfterValidator(_validate_us_state)]
"""Two-letter US state/territory code, normalized to upper-case."""
