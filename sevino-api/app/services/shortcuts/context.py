"""Inputs gathered once per request and shared across shortcut rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from app.services.shortcuts.time_buckets import TimeBucket


@dataclass(frozen=True)
class ShortcutContext:
    user_id: uuid.UUID
    bucket: TimeBucket
    day: date
    account_age_days: int
    conversation_count: int
