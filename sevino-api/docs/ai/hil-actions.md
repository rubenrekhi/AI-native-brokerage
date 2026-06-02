# Human-in-the-loop (HIL) actions

> Status: implemented. Deposits/withdrawals (`transfer_operations`) are the first consumer;
> the framework is feature-agnostic, so other actions named below (trades, order cancels,
> profile changes) are illustrative until built.

Some actions the AI can take are consequential: moving money, placing a trade, cancelling an
order, changing KYC details. These must never happen on the model's say-so alone — a human
has to explicitly approve each one. The HIL framework is the shared machinery that lets the
AI *propose* such an action and have it execute only after the user taps **Confirm** in the
app.

It is deliberately generic. A feature opts in by describing *what* it wants confirmed and
*how* to perform it; everything else — persistence, the confirmation card, the approval
endpoint, cancellation, the follow-up turn — is shared and identical across features.
Deposits and withdrawals are the first consumer; trades, order cancel/replace, position
closes, and profile changes can follow, each as just another `action_type`.

## Big picture

Three ideas, in one breath: **the model proposes, the user taps, the agent resumes.** A
consequential tool never executes — it returns a *proposal*. The runtime gates the turn,
persists it, and streams a confirmation card. When the user taps Confirm, the server performs
the action and the agent picks the conversation back up as a normal turn — so it feels like
the agent paused for the tap and continued (and it can call more tools).

It spans **two backend turns** with a tap between them, but **one continuous chat thread** to
the user:

```
  TURN 1 (the user's turn)                    TURN 2 (the confirm)
  ─────────────────────────                   ─────────────────────────
  user: "withdraw $200 to my bank"            user taps Confirm  (a button, not a message)
    model calls a propose_* tool                POST /actions/{id}
      runtime gates the turn:                     server claims the action (atomic CAS),
        • persist a pending_actions row             runs the handler's side effect,
        • stream a ConfirmationBlock card           then drives a FULL agent turn seeded
        • end turn `awaiting_confirmation`          with the handler's per-type prompt
                                                  → model narrates + may call more tools
```

Layered, most of it shared:

| Layer | Responsibility | Shared across features? |
|---|---|---|
| **Wire** | `ConfirmationBlock` (gen-UI card) + SSE events; iOS mirror | ✅ shared |
| **State** | `pending_actions` row — atomic-CAS source of truth, `effective_status`, supersede | ✅ shared |
| **Gate** | tool dispatch turns a proposal into a row + card + `awaiting_confirmation` | ✅ shared |
| **Confirm + resume** | endpoint claims the action, runs the handler, drives a system-initiated agent turn | ✅ shared |
| **Handler** | the side effect (`execute`) + per-type resume/reject prompts | ⬅ per feature |
| **Propose tool** | parse/validate inputs, build the card + `ProposedAction` | ⬅ per feature |

A new HIL action is just the bottom two rows: a propose tool and a handler. The four shared
layers are written once.

The rest of this doc walks each layer in detail.

## Propose, confirm, narrate

The lifecycle spans two backend turns with a user tap in between:

```
TURN 1 (user-initiated)                 CONFIRM (button tap)         TURN 2 (system-initiated)
─────────────────────────               ──────────────────           ─────────────────────────
user asks for an action                 user taps Confirm            (no user bubble)
 model calls a propose_* tool           POST /actions/{id}            run_agent_turn seeded with
   runtime persists pending_action        atomic CAS pending→confirmed   the handler's resume_prompt
   streams a ConfirmationBlock card       handler.execute (side effect)  → model narrates + may
 model emits closing text                drives a full agent turn ──────→  call more tools
 turn ends: awaiting_confirmation
        (e.g. "buy $500 AAPL", "withdraw $200 to my bank", "cancel order #123")
```

A "turn" is a backend accounting unit — one `agent_turn` row, one run of the model loop. It
is **not** a UX unit. The user sees a single continuous chat thread; the seam between the
two turns is invisible, for two reasons:

- Tapping **Confirm** is a button press, not a chat message, so no user bubble appears.
- The confirm request streams the assistant's reply back into the *same* thread immediately,
  so the bot simply "keeps talking" after the tap.

The crucial property: **the model is never given a tool that mutates anything.** It can only
*propose*. The actual side effect runs server-side in the confirm step, from a payload the
server persisted at propose time. The client sends only an `action_id` and a decision — it
cannot alter what executes between proposing and confirming. This holds for every action type.

## One conversation, two turns — not a suspended loop

It would seem natural to "pause" the agent loop while waiting for the tap and resume it after.
The app deliberately does not. Cross-turn history is **text-only**: when a new turn replays
the conversation, `to_anthropic_content` keeps only `text` blocks and drops tool calls and UI
blocks (its own note: *"tool-use context is also lost across turns; the assistant text is
sufficient continuity"*). So there is nothing to resume — turn 1 finishes cleanly, and turn 2
starts as a fresh message list seeded with what happened.

This keeps the system stateless and crash-safe. The only thing that survives between the tap
and the response is one database row; there is no in-memory loop state to checkpoint, and no
dangling tool call to stitch across the boundary.

## The pending action

A proposed-but-not-yet-executed action is a row in `pending_actions` (Postgres). It lives in
the database rather than Redis because it is a durable financial and audit record, not
ephemeral cache state — the same reason `cache.py` keeps authoritative values out of the cache.

```
id              uuid pk
user_id         uuid
conversation_id uuid
agent_turn_id   uuid
tool_use_id     text          -- the proposing tool call (audit linkage)
action_type     text          -- "transfer", "place_order", ... — selects the handler
payload         jsonb         -- resolved, deterministic args; executed verbatim server-side
preview         jsonb         -- exactly what the card showed the user (audit / tamper evidence)
status          text          -- written events only (see below)
result          jsonb         -- the handler's outcome (summary)
expires_at      timestamptz   -- per-action window
confirmed_at / executed_at / rejected_at / superseded_at
created_at / updated_at
```

`action_type` is the only field that varies between features — the table and every transition
are identical for all of them. Each action chooses its own expiry window: a trade is short
(prices move), a profile change can be long.

### Status is partly written, partly derived

There are two kinds of "how a proposal ends," and they are represented differently:

- **Expiry is time-derived.** Whether a proposal has timed out is a pure function of
  `expires_at` and the current time, so it is never stored — it is computed on read.
- **Everything else is event-driven.** Confirming, rejecting, or superseding is caused by a
  tap or a message, so it is written to `status`.

```python
def effective_status(row) -> str:
    if row.status == "pending" and row.expires_at <= now():
        return "expired"                 # derived (time)
    return row.status                    # written: pending|confirmed|rejected|superseded|executed|failed
```

Because expiry is derived, nothing needs to sweep the table to mark rows expired — there is no
cron. (One could be added later purely so `expired` becomes a queryable stored value for
analytics, but it is not required for correctness.)

### Lifecycle

```
pending ──► confirmed ──► executed | failed   (user tapped Confirm)
        ──► rejected                            (user tapped Cancel)
        ──► superseded                          (user sent another message instead)
        ──► expired (derived)                   (window lapsed, untouched)
```

The three "did not happen" outcomes are kept distinct on purpose: `rejected` is an active
decline, `superseded` is the user moving on without deciding, and `expired` is a timeout. They
look the same to the user (a dead card) but mean different things in the audit trail.

## Atomic confirmation — the correctness backbone

Every state change is a guarded compare-and-swap on `status='pending'`, serialized by the
row lock:

```sql
UPDATE pending_actions SET status='confirmed', confirmed_at=now()
WHERE id=:id AND status='pending' AND expires_at>now()
RETURNING *;        -- 0 rows => already confirmed / expired / superseded / gone
```

This one pattern is what makes the whole system safe. A double-tap, a tap after expiry, and a
tap that races against cancellation all resolve to "exactly one transition wins" without any
extra locking. An action can only execute if its CAS to `confirmed` succeeded, so a stale or
already-resolved proposal physically cannot fire.

## Cancellation and safety

### Sending a message cancels live proposals

A proposal is meant to be confirmed *now*. If the user types another message instead of
tapping, the proposal is cancelled rather than left hanging. This happens deterministically at
the start of every **user-initiated** turn, before the model runs:

```sql
UPDATE pending_actions SET status='superseded', superseded_at=now()
WHERE conversation_id=:cid AND status='pending' AND expires_at>now();
```

It is a server-side rule, not a model decision — the same principle as execution being
server-authoritative. The system-initiated confirm turn (which has no user message) does not
trigger it, and an action already mid-confirmation is untouched because its CAS has already
moved it off `pending`.

### Cards stop being clickable

A `ConfirmationBlock` is streamed in turn 1 and persisted in the conversation history, so a
dead proposal's card must not remain tappable. The card therefore does **not** store its own
status; it stores only the `action_id`. The live status is resolved when history is read — the
serializer joins `pending_actions` and stamps the current `effective_status`, and the card is
interactive only while that is `pending`. This stays correct after a reload or on a second
device.

During a live session the app also deadens the card locally the instant the user taps Send, so
the feedback is immediate; the read-time resolution is the durable source of truth. (The two
agree because both react to the same event — the new message.) This avoids trying to mutate a
closed historical block over the stream, which the wire format does not support.

### Confirmation is button-only

A consequential action never executes from natural-language consent — only from an explicit
tap on a live proposal. If the user types "yes, do it" instead of tapping, two things combine:
the supersede rule has already killed the original card, and the model (guided by its system
prompt) responds by explaining that an explicit tap is required *and* re-proposing a fresh
card. Re-proposing rebuilds the proposal from current state — re-pricing a trade, re-checking a
limit — so the user never confirms something stale.

The safety rule stays simple and content-blind (any message supersedes), while the helpful
part (explain, then offer a fresh card) lives in the model's reply. Notably, even if the model
misbehaves here, the worst case is a redundant re-proposal — it has no way to execute anything,
because it has no execution tool.

## Executing and resuming the conversation

A confirmation resumes the chat as a **full, system-initiated agent turn**. To the user it
looks like the agent paused for them to confirm, they held to confirm, and the agent picked the
conversation back up — and it can call more tools. There is no canned line.

On confirm, the runtime dispatches on `action_type` to the matching handler, runs its side
effect (`execute`), then drives `run_agent_turn` seeded with the handler's `resume_prompt` — a
synthetic, model-only message describing what the user confirmed and how it went ("the user
confirmed the $500 deposit you proposed; it went through"). The model narrates from that and may
call further tools. The seed is **per-action-type**, not generic: each handler writes its own
success/failure phrasing, and the authoritative facts live in that seed (sourced from the
handler's `execute` result), so the model relays them rather than inventing.

The turn is system-initiated: no user bubble is persisted (the user tapped a button, not typed)
and the supersede sweep is skipped (the confirmed action is already off `pending`, and a confirm
shouldn't cancel unrelated proposals). On **reject**, the same kind of turn is driven, seeded
with the handler's `reject_prompt`. If execution fails, the seed says so and the model explains
what happened and what to do next — never claiming success.

## How features extend the system

The framework owns everything generic: the `pending_actions` table and its transitions, the
runtime gate that turns a proposal into a persisted row + a streamed card + an
`awaiting_confirmation` turn end, the confirm endpoint, cancellation, expiry, and narration.

A feature contributes just two things:

- **A propose tool** — a normal AI tool that does the safe preparation (validate inputs,
  compute a preview/estimate) and, instead of acting, returns a `ProposedAction` describing
  what should execute, alongside the `ConfirmationBlock` the user will see.
- **A handler** — registered under the action's `action_type`. It performs the side effect
  (`execute`, returning an `ActionResult` whose `resume_prompt` seeds the follow-up turn) and
  supplies the `reject_prompt` for the cancel path. Both messages are the handler's own —
  distinct per action type, not generic.

Optionally it adds a bespoke card `kind` (with a matching iOS layout) and a system-prompt
snippet describing when to propose the action; absent those, the generic card layout is used.

The seams are these contracts:

```python
class ProposedAction(BaseModel):
    action_type: str            # selects the handler
    payload: dict[str, Any]     # resolved, deterministic args
    expires_in_s: int = 300     # per-action window

# A tool signals "gate this turn" by returning a proposal on its result:
class ToolResult(BaseModel):
    model_payload: dict[str, Any]
    ui_block: Block | None = None
    internal_trace: dict[str, Any] | None = None
    proposal: ProposedAction | None = None     # presence raises the HIL gate

class ConfirmationBlock(BaseModel):            # the gen-UI card (in the Block union)
    type: Literal["confirmation"] = "confirmation"
    block_id: str
    action_id: str                             # what Confirm posts back
    kind: str                                  # iOS picks a layout; generic fallback
    title: str
    rows: list[ConfirmationRow]                # label/value lines, used by all actions
    details: dict[str, Any] = {}               # kind-specific payload, opaque to framework
    confirm_label: str = "Confirm"
    cancel_label: str = "Cancel"
    hold_to_confirm: bool = True               # iOS renders hold-to-confirm vs. tap
    status: str = "pending"                    # on the wire; re-stamped at read time

class ActionResult(BaseModel):                 # outcome of execute()
    status: Literal["executed", "failed"]
    resume_prompt: str                         # per-type seed for the follow-up turn
    summary: dict[str, Any]                    # persisted to pending_actions.result

class ActionHandler(Protocol):                 # one per action_type
    async def execute(self, payload, ctx) -> ActionResult: ...
    def reject_prompt(self, payload) -> str: ...

ACTION_HANDLERS: dict[str, ActionHandler] = {
    "transfer": TransferActionHandler(),
    # "place_order": PlaceOrderActionHandler(),
}
```

### Worked example: transfers (the first consumer)

Deposits/withdrawals are an ordinary instance of the above. A `TransferOperations` tool
validates the amount and resolves the source bank (asking which when the user has several),
returning a `ProposedAction(action_type="transfer")` with a `ConfirmationBlock(kind="transfer")`.
Its handler, `TransferActionHandler`, calls the existing `FundingService.create_transfer` →
Alpaca on confirm and returns an `ActionResult` whose `resume_prompt` tells the model the
transfer went through — or, on failure, a user-safe reason (raw Alpaca/network text is logged,
never surfaced); `reject_prompt` covers the cancel path. No confirmation plumbing is specific to
transfers; a trade or order-cancel consumer would be the same shape against its own APIs.

## How it maps onto the codebase

| Concept | Location |
|---|---|
| `ConfirmationBlock` (+ iOS mirror) | `app/ai/blocks.py`, `Models/Chat/Block.swift` |
| Proposal interrupt on tool results | `app/ai/tools/base.py` (`ProposedAction`, `ToolResult.proposal`) |
| The gate (proposal → persisted row + card + turn end) | tool dispatch in `app/ai/runtime/dispatch`, `runtime/flow/iteration.py` |
| `awaiting_confirmation` turn end; system-initiated turn (`persist_user_message=False`) | `app/ai/runtime/loop.py`, `runtime/flow/turn_lifecycle.py` |
| Supersede sweep at turn start | `app/ai/runtime/flow/turn_lifecycle.py` |
| Read-time card-status resolution | conversation/message history serialization |
| Pending-action state + transitions | `app/models/pending_action.py` + repository |
| Handler registry (`ActionHandler` + `ActionResult`) | `app/ai/actions/` (`transfer.py` = first handler) |
| Confirm endpoint | `app/routes/actions.py` (`POST /v1/conversations/{id}/actions/{action_id}`) |
