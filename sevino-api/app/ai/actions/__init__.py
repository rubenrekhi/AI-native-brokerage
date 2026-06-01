"""Executor registry for human-in-the-loop actions.

A consequential tool proposes an action (``ToolResult.proposal``); on user
confirm the route dispatches on ``action_type`` to the matching executor here.
The framework owns the gate, persistence, and confirm endpoint; a feature only
adds a propose tool + an executor registered below.
"""

from app.ai.actions.base import ActionContext, ActionExecutor, ActionResult

ACTION_EXECUTORS: dict[str, ActionExecutor] = {}


def register_action_executor(
    action_type: str, executor: ActionExecutor
) -> None:
    if action_type in ACTION_EXECUTORS:
        raise ValueError(
            f"Action executor {action_type!r} is already registered"
        )
    ACTION_EXECUTORS[action_type] = executor


def get_action_executor(action_type: str) -> ActionExecutor:
    try:
        return ACTION_EXECUTORS[action_type]
    except KeyError as exc:
        raise KeyError(
            f"No executor registered for action_type {action_type!r}"
        ) from exc


__all__ = [
    "ACTION_EXECUTORS",
    "ActionContext",
    "ActionExecutor",
    "ActionResult",
    "get_action_executor",
    "register_action_executor",
]
