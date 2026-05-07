"""Shared HTTP utilities for service-layer modules."""

import re

# Truncation limit for upstream response bodies in error logs. Keeps logs
# grep-able without dumping multi-KB payloads.
BODY_LOG_LIMIT = 500

_BEARER_RE = re.compile(r"Bearer\s+[\w.\-]+", re.IGNORECASE)


def redact_bearer(text: str) -> str:
    """Strip `Bearer <token>` segments from log output.

    Upstream error envelopes occasionally echo the request's `Authorization`
    header back; redacting before logging keeps tokens out of stdout.
    """
    if not text:
        return text
    return _BEARER_RE.sub("Bearer ***", text)
