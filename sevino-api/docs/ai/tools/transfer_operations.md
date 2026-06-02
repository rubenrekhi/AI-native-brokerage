# `transfer_operations`

Registered agent tool that **proposes** a deposit or withdrawal between the user's linked bank and their Sevino brokerage account. It is the first **human-in-the-loop (HIL)** tool: it never moves money. It validates the amount and resolves the source bank, then returns a `ConfirmationBlock` card plus a `ProposedAction`, and the turn ends awaiting the user's tap. The money moves only after the user confirms, when `TransferActionHandler` runs the ACH transfer in a separate turn. It is part of the harness tool layer — see [`../ai-harness.md`](../ai-harness.md) §6 for the generic `Tool` contract, dispatch, and audit flow, and **[`../hil-actions.md`](../hil-actions.md)** for the propose → confirm → narrate framework this tool plugs into.

One tool, two operations selected by `operation`: `deposit` moves money from the bank into Sevino (ACH `INCOMING`), `withdraw` moves it from Sevino back to the bank (ACH `OUTGOING`).

File paths are relative to `sevino-api/`.

| | |
|---|---|
| File · class | `app/ai/tools/transfer_operations.py` · `TransferOperations` |
| Handler (runs on confirm) | `app/ai/actions/transfer.py` · `TransferActionHandler`, keyed `action_type="transfer"` |
| Reads / writes | reads the user's **APPROVED** ACH relationships via `FundingService.list_active_ach_relationships`; **moves no money** — the transfer runs on confirm, not here |
| Freshness | live read of the user's linked banks (DB + Alpaca, via `FundingService`) |
| Status pill | **none** — unlike the read tools, this one emits no `StatusBlock`; its `ui_block` is the `ConfirmationBlock` card |
| Proposal | `ConfirmationBlock(kind="transfer")` + `ProposedAction(action_type="transfer")`, `expires_in_s=300` |
| Session | opens its own DB session from `ctx.db_factory` |

The model calls this when the user wants to move money — "deposit $500", "add money", "withdraw $200 to my bank", "take some cash out". It parses the dollar `amount`, picks `operation`, and passes `bank_hint` **only** when the user has more than one linked bank and named which one. It never tells the user the transfer is done, scheduled, or in progress from this call — the outcome comes back only after the tap. The system prompt (`app/ai/prompts/sevino_v1.md` §"Deposits and withdrawals (`transfer_operations`)" and §"Confirming consequential actions") owns this guidance.

---

## Input — `TransferOperationsInput`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `operation` | `deposit \| withdraw` | — (required) | `deposit` → money from bank into Sevino (`INCOMING`); `withdraw` → money from Sevino back to the bank (`OUTGOING`). |
| `amount` | `Decimal` (> 0) | — (required) | US dollars, parsed from the user's request. Quantized to cents before use (`500` → `"500.00"`). |
| `bank_hint` | `str \| None` | `None` | A nickname, institution name, or last-4 to disambiguate when the user has more than one linked bank. Omit for a single bank or when the user hasn't named one. Matched **case-insensitively as a substring** against nickname / institution / mask. |

---

## Output — `model_payload`

The tool returns one of three shapes. **None of them means money moved** — at most it means a card is now waiting for a tap.

### Proposal presented (success)

`{"status": "proposal_presented", "operation", "amount", "bank": {relationship_pk, nickname, institution, mask}}` — returned alongside the `ConfirmationBlock` card (`ui_block`) and the `ProposedAction` (`proposal`, which raises the HIL gate). This is as far as the tool goes; the turn ends `awaiting_confirmation`.

### Needs clarification

`{"status": "needs_clarification", "operation", "amount", "banks": [{relationship_pk, nickname, institution, mask}, ...]}` — several usable banks and the choice is unclear (no `bank_hint`, or a hint matching zero or multiple banks). **No card, no proposal.** The model asks which bank, then calls again with `bank_hint`.

### Error

`{"status": "error", "code", "error"}` — no card, no proposal:

| `code` | When | What the model does |
|---|---|---|
| `NO_LINKED_BANK` | the user has no linked bank at all | tell them to link a bank first |
| `BANK_NOT_APPROVED` | a bank is linked but still verifying (no relationship in `APPROVED`) | tell them the link is still being verified |
| `BROKERAGE_UNAVAILABLE` | the Alpaca client is absent (`ctx.http_clients.alpaca is None`) | tell them transfers are temporarily unavailable |

---

## Bank resolution

`execute` resolves exactly one source bank, or refuses:

1. List the user's active ACH relationships → none at all ⇒ `NO_LINKED_BANK`.
2. Keep only those in `APPROVED` status (`usable`) → none usable ⇒ `BANK_NOT_APPROVED`.
3. `_resolve_bank(usable, bank_hint)`:
   - **with `bank_hint`** — keep relationships whose nickname/institution/mask contains the hint; a **single** match wins, zero or multiple ⇒ `needs_clarification`.
   - **without `bank_hint`** — the **single** usable bank wins; more than one ⇒ `needs_clarification`.

There is no "soft success" here (contrast [`radar_operations`](radar_operations.md)): a transfer always requires an explicit, unambiguous bank and an explicit tap, so an ambiguous choice is bounced back rather than guessed.

---

## The proposal — card + action

On success the tool builds two artifacts that travel together; the HIL gate persists both before ending the turn.

**`ConfirmationBlock`** (`ui_block`, `kind="transfer"`) — what the user sees:

- `title` / `confirm_label`: "Confirm deposit" / "Confirm withdrawal".
- `rows`: `Amount` = `$500.00`; `Transfer` = `Chase ••1234 → Sevino` (deposit) or `Sevino → Chase ••1234` (withdraw).
- `details` (kind-specific, opaque to the framework, consumed by the iOS layout): `operation`, `direction`, `amount`, `currency` (`"USD"`), `bank_institution`, `bank_mask`, `bank_nickname`.
- `hold_to_confirm` defaults `true` (iOS renders hold-to-confirm).

**`ProposedAction`** (`proposal`, `action_type="transfer"`, `expires_in_s=300`) — what executes server-side on confirm. Its `payload` is the resolved, deterministic, executed-verbatim args: `relationship_pk`, `amount`, `direction`, `operation`, plus the **display-only** `bank_institution` / `bank_mask` / `bank_nickname` (carried so the result receipt can name the bank without a re-lookup). The client can't alter this payload between proposing and confirming.

The same `action_id` is stamped on both the card and the proposal — it is what `POST /v1/conversations/{conversation_id}/actions/{action_id}` posts back.

---

## No status pill

Unlike `get_stock_info`, `radar_operations`, `get_account_activity`, and the portfolio tools, this tool **emits no `StatusBlock`** — `execute` never touches `ctx.sse_emitter`. Its `ui_block` is the `ConfirmationBlock` card itself (streamed by the gate). There is no "active → complete" pill because the tool's work — *proposing* — is finished the moment the card appears; the actual transfer is a separate, user-triggered step in another turn.

---

## The HIL gate & lifecycle

The `proposal` on the `ToolResult` is what makes this tool consequential. When tool dispatch sees a proposal came back (`tool_outcomes.proposal_raised`), the iteration ends the turn `awaiting_confirmation` instead of feeding a `tool_result` back to the model (`app/ai/runtime/flow/iteration.py`): the runtime persists a `pending_actions` row, the card is already in the streamed and persisted assistant blocks, and the turn stops. Nothing else runs until the user taps.

On **confirm**, `POST …/actions/{action_id}` atomically claims the row (CAS on `status='pending'`) and dispatches on `action_type` to `TransferActionHandler`:

- `execute` runs `FundingService.create_transfer` (→ Alpaca) and returns an `ActionResult` whose `resume_prompt` seeds a fresh, system-initiated agent turn telling the model the transfer went through — or, on failure, a **user-safe** reason (raw Alpaca/network text is logged, never surfaced).
- `reject_prompt` seeds the same kind of turn on **cancel**.

The shared propose → confirm → narrate machinery — the `pending_actions` table, atomic CAS, supersede-on-new-message, expiry, and the resume turn — lives in **[`../hil-actions.md`](../hil-actions.md)**. This tool and `TransferActionHandler` are the two feature-specific pieces; everything else is generic.

### Not yet supported: cancel

Cancelling a pending transfer is a planned third operation but is **not built** — its execution layer (`FundingService.cancel_transfer`) does not exist yet. The tool today exposes only `deposit` and `withdraw`.

---

## Wire & iOS mirror

`ConfirmationBlock` / `ConfirmationRow` are variants of the `Block` union (`app/ai/blocks.py`), hand-mirrored in iOS (`Models/Chat/Block.swift`; covered by `SevinoTests/Chat/ConfirmationBlockTests.swift`). iOS picks a typed layout off `kind="transfer"`, reading the `details` map. Per [`../ai-harness.md`](../ai-harness.md) §8 this is a **real wire variant**, so any change to `ConfirmationBlock` must update the Swift mirror in the same PR.

---

## Wiring

- **Registration** — registered in `build_default_registry()` (`app/ai/tools/__init__.py`), so it's offered on every turn.
- **Handler** — `TransferActionHandler` registered under `action_type="transfer"` via `register_action_handler` in `app/ai/actions/__init__.py` (`ACTION_HANDLERS`).
- **Clients** — needs `ToolHttpClients.alpaca` (`None` → `BROKERAGE_UNAVAILABLE`). Reads banks via `FundingService`, the same service behind the REST funding endpoints.
- **System prompt** — `app/ai/prompts/sevino_v1.md` §"Deposits and withdrawals (`transfer_operations`)" and §"Confirming consequential actions".
- **Tests** — `tests/ai/unit/test_transfer_operations_tool.py` (propose tool), `tests/ai/unit/test_transfer_action_executor.py` (handler), `tests/ai/integration/test_actions_route_sse.py` (confirm endpoint + SSE), `tests/integration/test_pending_action_repository.py` (pending-action state).
