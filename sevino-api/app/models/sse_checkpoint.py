from typing import Optional

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SseCheckpoint(Base, TimestampMixin):
    __tablename__ = "sse_checkpoints"

    stream_name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_event_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
