"""Deterministic per-(user, day, bucket) rotation of template lists.

Uses SHA-256 rather than the builtin ``hash()``: the latter is salted per
interpreter process (``PYTHONHASHSEED``), so its results differ across
restarts and worker processes. Rotation must be stable so the 30s cache
and the client agree on a single ordering for a given day.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date

from app.services.shortcuts.time_buckets import TimeBucket


def rotate(
    items: list[str], *, user_id: uuid.UUID, day: date, bucket: TimeBucket
) -> list[str]:
    if not items:
        return []
    seed = f"{user_id}:{day.isoformat()}:{bucket.value}"
    offset = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(items)
    return items[offset:] + items[:offset]
