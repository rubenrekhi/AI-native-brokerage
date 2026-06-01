"""Contracts for human-in-the-loop action handlers.

On confirm the framework runs `execute` (the side effect) and seeds a full
follow-up agent turn with `resume_prompt`; on reject it seeds the turn with
`reject_prompt`. The resume/reject messages are per-action-type, not generic —
each handler describes its own outcome to the model, which then narrates and
may call further tools (see docs/ai/hil-actions.md).
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.ai.runtime.db import DbSessionFactory
from app.ai.tools.base import ToolHttpClients


class ActionContext:
    """Execution context handed to an action handler."""

    __slots__ = ("user_id", "db_factory", "http_clients")

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        db_factory: DbSessionFactory,
        http_clients: ToolHttpClients,
    ) -> None:
        self.user_id = user_id
        self.db_factory = db_factory
        self.http_clients = http_clients


class ActionResult(BaseModel):
    """Outcome of executing a confirmed action.

    ``resume_prompt`` seeds the follow-up agent turn — a synthetic, model-only
    message describing what the user confirmed and how it went. ``summary`` is
    persisted to ``pending_actions.result`` for audit.
    """

    status: Literal["executed", "failed"]
    resume_prompt: str
    summary: dict[str, Any] = Field(default_factory=dict)


class ActionHandler(Protocol):
    """Per-action-type behaviour for the HIL confirm endpoint."""

    async def execute(
        self, payload: dict[str, Any], ctx: ActionContext
    ) -> ActionResult: ...

    def reject_prompt(self, payload: dict[str, Any]) -> str: ...
