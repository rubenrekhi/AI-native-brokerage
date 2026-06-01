"""Contracts for human-in-the-loop action executors.

An executor performs the side effect of a confirmed ``PendingAction`` and
returns its authoritative result. The result card renders from this — never
from model free-text (see docs/ai/hil-actions.md §"facts vs. framing").
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.ai.blocks import Block
from app.ai.runtime.db import DbSessionFactory
from app.ai.tools.base import ToolHttpClients


@dataclass(frozen=True, slots=True)
class ActionContext:
    user_id: uuid.UUID
    db_factory: DbSessionFactory
    http_clients: ToolHttpClients


class ActionResult(BaseModel):
    status: Literal["executed", "failed"]
    result_block: Block | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    narration: str


ActionExecutor = Callable[
    [dict[str, Any], ActionContext], Awaitable[ActionResult]
]
