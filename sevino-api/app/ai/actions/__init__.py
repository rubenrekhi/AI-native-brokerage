"""Handler registry for human-in-the-loop actions.

A consequential tool proposes an action (``ToolResult.proposal``); on user
confirm the route dispatches on ``action_type`` to the matching handler here,
runs its side effect, and drives a full follow-up agent turn seeded by the
handler's per-type resume/reject prompt. The framework owns the gate,
persistence, confirm endpoint, and the follow-up turn; a feature only adds a
propose tool + a handler registered below.
"""

from app.ai.actions.base import ActionContext, ActionHandler, ActionResult

ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_action_handler(
    action_type: str, handler: ActionHandler
) -> None:
    if action_type in ACTION_HANDLERS:
        raise ValueError(
            f"Action handler {action_type!r} is already registered"
        )
    ACTION_HANDLERS[action_type] = handler


def get_action_handler(action_type: str) -> ActionHandler:
    try:
        return ACTION_HANDLERS[action_type]
    except KeyError as exc:
        raise KeyError(
            f"No handler registered for action_type {action_type!r}"
        ) from exc


# Register first-party handlers (import for side effect). Bottom of the module
# so the registry helpers above are defined first; handler modules import only
# ``app.ai.actions.base``, so this doesn't cycle.
from app.ai.actions.transfer import TransferActionHandler  # noqa: E402

register_action_handler("transfer", TransferActionHandler())

__all__ = [
    "ACTION_HANDLERS",
    "ActionContext",
    "ActionHandler",
    "ActionResult",
    "get_action_handler",
    "register_action_handler",
]
