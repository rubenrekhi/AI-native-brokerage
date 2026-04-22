from typing import Optional

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SseCheckpoint(Base, TimestampMixin):
    __tablename__ = "sse_checkpoints"

    stream_name: Mapped[str] = mapped_column(Text, primary_key=True)
    # Stores the ULID extracted from the event JSON payload (event_ulid for
    # legacy endpoints, event_id for already-migrated v2 endpoints). Named
    # last_event_id for historical reasons; the value is always a ULID string.
    last_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
