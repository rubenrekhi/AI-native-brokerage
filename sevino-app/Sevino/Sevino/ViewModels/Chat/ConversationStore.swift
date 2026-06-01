import Foundation
import os.log

/**
 Owns one conversation's UI state — message list, in-flight turn state, and
 the SSE consumption loop that streams agent events back from the chat-turn
 endpoint.

 Lifecycle: one instance per active conversation. `send(text:)` opens an SSE
 stream via `SSEClient`, optimistically appends the user's message, and
 mutates the assistant message in place as `block_start` / `text_delta` /
 `block_data` / `block_end` events arrive. `turn_completed` closes the turn
 cleanly; `error` parks the store in an error state for the UI to surface.

 `@Observable @MainActor`: views observe `messages` / `state` directly and
 all mutation runs on the main actor, so the chain `event arrives → store
 mutates → SwiftUI re-renders` does not cross actor boundaries. The SSE
 consumer task hops back to MainActor on every iteration via the structured-
 concurrency contract — there is no manual `MainActor.run`.
 */
@Observable
@MainActor
final class ConversationStore {

    /// Coarse turn-level state. `error` carries a closed-taxonomy code (so the
    /// view can decide *what* to render) and an optional human message (for
    /// the body copy of an alert / toast).
    enum TurnState: Equatable, Sendable {
        case idle
        case streaming
        case error(SSEEvent.ErrorCode, String?)
    }

    /// Conversation history rendered by `MessageListView` (C4.4). `var blocks`
    /// on each `Message` is mutated in place during streaming; the message id
    /// is fixed at append time.
    private(set) var messages: [Message] = []

    /// Coarse turn state — drives the input bar's loading affordance, the
    /// error banner, and the keyboard dismissal hook.
    private(set) var state: TurnState = .idle

    /// `turn_id` from the most recent `turn_started` event. Lifecycle:
    /// `nil` between turns; set on `turn_started`; cleared in `send(text:)`'s
    /// cleanup `defer` regardless of how the turn ends. Read it from views
    /// that need to correlate UI affordances with the *active* turn (e.g. a
    /// per-turn cancel button); after `turn_completed` it is `nil` again so
    /// a stale id never leaks into the next request.
    private(set) var currentTurnId: UUID?

    private let sseClient: any SSEClientProtocol
    let conversationId: UUID
    private let baseURL: String
    private let idempotencyKeyFactory: @Sendable () -> String
    private let timeZoneIdentifierProvider: @Sendable () -> String
    private let apiClient: any APIClientProtocol

    /// Default `JSONDecoder` for `SSEEvent`. The event payload structs declare
    /// explicit `CodingKeys` (e.g. `turnId = "turn_id"`) that *only* match
    /// when the decoder leaves JSON keys untouched — `convertFromSnakeCase`
    /// would transform `turn_id` to `turnId` before lookup and miss the
    /// explicit mapping. Locked to a property to match the strategy used in
    /// `SSEEventTests`.
    private let eventDecoder = JSONDecoder()
    /// `Block` relies on the project-wide snake_case ↔ camelCase strategy
    /// (see `JSONCoders+Sevino.swift`). Used to round-trip `block_start` /
    /// `block_data` payloads from `JSONValue` into typed blocks.
    private let blockDecoder = JSONDecoder.sevino()
    private let encoder = JSONEncoder.sevino()
    /// `TurnRequestBody` carries opaque context dictionaries whose keys must
    /// survive unchanged; snake_case is handled by explicit `CodingKeys`.
    private let requestEncoder = JSONEncoder()

    /// id of the assistant `Message` currently being populated by SSE events,
    /// or `nil` between turns. Stored separately from `messages.last?.id` so a
    /// stray pre-`turn_started` event can't accidentally mutate the user's
    /// optimistic message.
    private var currentAssistantMessageId: UUID?

    private static let logger = Logger(subsystem: "ai.sevino.Sevino", category: "ConversationStore")

    init(
        conversationId: UUID = UUID(),
        sseClient: any SSEClientProtocol = SSEClient(
            tokenProvider: { await (AuthService.shared as AuthServiceProtocol).accessToken }
        ),
        baseURL: String = AppConfig.apiBaseURL,
        idempotencyKeyFactory: @escaping @Sendable () -> String = { UUID().uuidString },
        timeZoneIdentifierProvider: @escaping @Sendable () -> String = { TimeZone.current.identifier },
        apiClient: any APIClientProtocol = APIClient.shared
    ) {
        self.conversationId = conversationId
        self.sseClient = sseClient
        self.baseURL = baseURL
        self.idempotencyKeyFactory = idempotencyKeyFactory
        self.timeZoneIdentifierProvider = timeZoneIdentifierProvider
        self.apiClient = apiClient
    }

    /**
     Replace `messages` with the persisted transcript for `conversationId`.

     Calls `GET /v1/conversations/{id}/messages` and rebuilds the in-memory
     message list from the JSONB-persisted blocks. Used by the sidebar's
     tap-to-resume flow: a new store is constructed with the chosen
     conversation id, then `load()` populates it before the chat surface
     comes into view.

     For v0 the loop only persists `text` blocks; future block types
     (status pills, stock cards) will need their own persistence policy
     (see SEV-571 for thinking blocks). Unknown block payloads log and are
     dropped — a single decode failure won't tear down the whole resume.

     Pagination intentionally not threaded through to the UI: typical
     conversations fit in one page (50 messages) and infinite-scroll is a
     follow-up. The `next_cursor` field is dropped here; if a transcript
     overflows one page the client only sees the oldest 50 turns until the
     follow-up lands.

     Throws on transport / decode failures and parks `state` in `.error`
     (matching `send(text:)`'s pattern) so the view layer has one shape to
     handle regardless of which API surface raised.
     */
    func load() async throws {
        let path = "/v1/conversations/\(conversationId.uuidString.lowercased())/messages"
        do {
            let response: ConversationMessagesDTO = try await apiClient.get(path)
            messages = response.items.map(buildMessage(from:))
            state = .idle
        } catch {
            state = .error(.internalError, error.localizedDescription)
            throw error
        }
    }

    /// Translate one wire-format `MessageDTO` into a UI `Message`. Decode
    /// failures on individual blocks are swallowed (logged in DEBUG) so a
    /// single malformed block doesn't drop the whole message — the user
    /// still sees the rest of the transcript around the bad row.
    /// Reuses the cached `encoder`/`blockDecoder` from `self` so a 50-
    /// message resume doesn't allocate a hundred fresh coders.
    ///
    /// The persisted `ContextBlock` (`type: "context"`) is a user attachment,
    /// not a streamed `Block` variant, so it's intercepted before the `Block`
    /// decoder rejects it and mapped onto `Message.attachedContext` — that
    /// re-renders the chip on resume (SEV-615). An unknown kind / malformed
    /// payload leaves the chip nil but keeps the rest of the message.
    private func buildMessage(from dto: MessageDTO) -> Message {
        let role = Role(rawValue: dto.role) ?? .assistant
        var attachedContext: AttachedContext?
        var blocks: [Block] = []
        for raw in dto.contentBlocks {
            if case .object(let obj) = raw, case .string("context")? = obj["type"] {
                attachedContext = AttachedContext.fromPersisted(raw, encoder: encoder)
                continue
            }
            do {
                let data = try encoder.encode(raw)
                blocks.append(try blockDecoder.decode(Block.self, from: data))
            } catch {
                #if DEBUG
                Self.logger.error("resume: dropped malformed block: \(String(describing: error), privacy: .public)")
                #endif
            }
        }
        return Message(id: dto.id, role: role, blocks: blocks, attachedContext: attachedContext)
    }

    /**
     Sends `text` as a new user turn and consumes the SSE stream.

     The user's message is appended *before* the network call so the input bar
     can clear synchronously. The corresponding assistant message is appended
     when `turn_started` arrives — not pre-emptively — so a request that fails
     before the server emits the first frame leaves no orphan empty bubble.

     Throws `URLError(.badURL)` if `baseURL` produces an invalid URL,
     `SSEClientError.httpStatus` for non-2xx responses, `URLError` for transport
     failures, or `CancellationError` when the calling task is cancelled. The
     `state` is updated to mirror the throw — callers don't need to set it
     themselves; they just propagate or swallow the error.

     `idempotencyKey` defaults to a fresh UUID minted via `idempotencyKeyFactory`.
     Pass an explicit key when retrying a failed turn so the backend (B3.2 idempotency
     slot) replays the persisted assistant message instead of re-running the agent.
     */
    func send(
        text: String,
        context: [String: JSONValue]? = nil,
        digestCard: ChatDigestCard? = nil,
        attachedContext: AttachedContext? = nil,
        idempotencyKey: String? = nil
    ) async throws {
        // A new user message supersedes any hanging proposal — deaden its card
        // locally so it can't be tapped (the backend's supersede sweep does the
        // same server-side; read-time resolution confirms it on reload).
        supersedeLocalPendingConfirmations()

        // SEV-615 B: a digest card rides the unified `context` channel as
        // `kind=digest` (its payload is the opaque `data`), instead of a
        // separate `digest_card` field. The source chip renders above the
        // user bubble from this locally-derived source; `turn_started` may
        // override it with the backend's authoritative value.
        let userMessage = Message(
            id: UUID(),
            role: .user,
            blocks: [.text(TextBlock(blockId: UUID().uuidString, text: text))],
            cardContextSource: digestCard.flatMap(CardContextSource.init),
            attachedContext: attachedContext
        )
        messages.append(userMessage)

        let effectiveContext: [String: JSONValue]? = digestCard.map { card in
            ["kind": .string("digest"), "data": .object(card.payload)]
        } ?? context

        let request = try buildRequest(
            message: text,
            context: effectiveContext,
            idempotencyKey: idempotencyKey ?? idempotencyKeyFactory()
        )
        state = .streaming
        currentAssistantMessageId = nil

        defer {
            currentAssistantMessageId = nil
            currentTurnId = nil
        }

        do {
            for try await raw in sseClient.stream(request: request) {
                try Task.checkCancellation()
                guard let payload = raw.data.data(using: .utf8) else {
                    Self.logger.error("Skipping SSE frame with non-UTF-8 data")
                    continue
                }
                let event = try SSEEvent.decode(from: payload, decoder: eventDecoder)
                apply(event)
                if case .error = state { return }
            }
            // Stream finished. If the consuming task was cancelled, surface
            // CancellationError to the caller; otherwise reset to idle so the
            // next send isn't blocked behind a phantom in-flight turn.
            try Task.checkCancellation()
            if case .streaming = state {
                state = .idle
            }
        } catch is CancellationError {
            state = .idle
            throw CancellationError()
        } catch {
            // Map transport / decode failures to the closed `internal_error`
            // bucket so views have a single switch over `SSEEvent.ErrorCode`
            // regardless of which layer raised.
            state = .error(.internalError, error.localizedDescription)
            throw error
        }
    }

    /**
     Confirm or reject a pending HIL action (e.g. a proposed transfer).

     `POST`s `{decision}` to `/v1/conversations/{id}/actions/{actionId}` and
     consumes the resulting SSE turn exactly as `send(text:)` does — the server
     streams the executed/failed result back as a fresh assistant message. No
     user bubble is appended: tapping a card is not a chat message. The tapped
     card is deadened locally up front so it can't be double-submitted.
     */
    func submitAction(actionId: String, decision: String) async throws {
        markLocalConfirmation(
            actionId: actionId,
            status: decision == "reject" ? "rejected" : "confirmed"
        )
        let request = try buildActionRequest(
            actionId: actionId, decision: decision
        )
        state = .streaming
        currentAssistantMessageId = nil

        defer {
            currentAssistantMessageId = nil
            currentTurnId = nil
        }

        do {
            for try await raw in sseClient.stream(request: request) {
                try Task.checkCancellation()
                guard let payload = raw.data.data(using: .utf8) else {
                    Self.logger.error("Skipping SSE frame with non-UTF-8 data")
                    continue
                }
                let event = try SSEEvent.decode(from: payload, decoder: eventDecoder)
                apply(event)
                if case .error = state { return }
            }
            try Task.checkCancellation()
            if case .streaming = state {
                state = .idle
            }
        } catch is CancellationError {
            state = .idle
            throw CancellationError()
        } catch {
            state = .error(.internalError, error.localizedDescription)
            throw error
        }
    }

    /// Flip every still-pending confirmation card to `superseded` in place.
    private func supersedeLocalPendingConfirmations() {
        rewriteConfirmations { cb in
            cb.isPending ? cb.withStatus("superseded") : nil
        }
    }

    /// Flip the pending card with `actionId` to `status` in place.
    private func markLocalConfirmation(actionId: String, status: String) {
        rewriteConfirmations { cb in
            cb.isPending && cb.actionId == actionId
                ? cb.withStatus(status)
                : nil
        }
    }

    /// Apply `transform` to every confirmation block; a non-nil return replaces
    /// it. Keeps the two local-deaden helpers DRY.
    private func rewriteConfirmations(
        _ transform: (ConfirmationBlock) -> ConfirmationBlock?
    ) {
        for i in messages.indices {
            var blocks = messages[i].blocks
            var changed = false
            for j in blocks.indices {
                if case .confirmation(let cb) = blocks[j],
                   let replacement = transform(cb) {
                    blocks[j] = .confirmation(replacement)
                    changed = true
                }
            }
            if changed { messages[i].blocks = blocks }
        }
    }

    private func apply(_ event: SSEEvent) {
        switch event {
        case .turnStarted(let payload):
            currentTurnId = payload.turnId
            if let source = payload.cardContextSource,
               let index = messages.lastIndex(where: { $0.role == .user }) {
                messages[index].cardContextSource = source
            }
            let id = UUID()
            currentAssistantMessageId = id
            messages.append(Message(id: id, role: .assistant, blocks: []))

        case .status:
            // Turn-level status notes are reserved for future use; v0 renders
            // status pills from `StatusBlock` blocks (carried on `block_start`
            // / `block_data`), not from this event.
            break

        case .blockStart(let payload):
            guard let block = decodeBlock(from: payload.block) else { return }
            mutateAssistantMessage { message in
                message.blocks.append(block)
            }

        case .textDelta(let payload):
            mutateAssistantMessage { message in
                guard let index = message.blocks.firstIndex(where: { $0.blockId == payload.blockId }) else {
                    Self.logger.error("text_delta references unknown block id")
                    return
                }
                switch message.blocks[index] {
                case .text(let block):
                    message.blocks[index] = .text(
                        TextBlock(blockId: block.blockId, text: block.text + payload.text)
                    )
                case .thinking(let block):
                    // SEV-571: backend forwards `thinking_delta` chunks
                    // as `text_delta` events targeting the thinking
                    // block's id, so the append happens here too.
                    message.blocks[index] = .thinking(
                        ThinkingBlock(
                            blockId: block.blockId,
                            text: block.text + payload.text,
                            redacted: block.redacted,
                            state: block.state
                        )
                    )
                case .status:
                    Self.logger.error(
                        "text_delta targeted .status block id=\(payload.blockId, privacy: .public)"
                    )
                case .stockCard:
                    Self.logger.error(
                        "text_delta targeted .stockCard block id=\(payload.blockId, privacy: .public)"
                    )
                case .recurringInvestmentSetup:
                    Self.logger.error(
                        "text_delta targeted .recurringInvestmentSetup block id=\(payload.blockId, privacy: .public)"
                    )
                case .cancelTransfer:
                    Self.logger.error(
                        "text_delta targeted .cancelTransfer block id=\(payload.blockId, privacy: .public)"
                    )
                case .cancelOrder:
                    Self.logger.error(
                        "text_delta targeted .cancelOrder block id=\(payload.blockId, privacy: .public)"
                    )
                case .stockComparison:
                    Self.logger.error(
                        "text_delta targeted .stockComparison block id=\(payload.blockId, privacy: .public)"
                    )
                case .confirmation:
                    Self.logger.error(
                        "text_delta targeted .confirmation block id=\(payload.blockId, privacy: .public)"
                    )
                }
            }

        case .blockData(let payload):
            mutateAssistantMessage { message in
                guard let index = message.blocks.firstIndex(where: { $0.blockId == payload.blockId }) else {
                    Self.logger.error("block_data references unknown block id")
                    return
                }
                guard let merged = mergePatch(into: message.blocks[index], patch: payload.data) else {
                    return
                }
                message.blocks[index] = merged
            }

        case .blockEnd:
            // Block finalization is implicit in v0 — no per-block terminal
            // state on `Block`. The case is kept exhaustive so a future
            // "completed" flag on TextBlock / StatusBlock has an obvious
            // mutation site.
            break

        case .turnCompleted:
            state = .idle

        case .error(let payload):
            state = .error(payload.code, payload.message)
        }
    }

    private func mutateAssistantMessage(_ apply: (inout Message) -> Void) {
        guard let id = currentAssistantMessageId,
              let index = messages.firstIndex(where: { $0.id == id }) else {
            Self.logger.error("Block event arrived without a current assistant message")
            return
        }
        apply(&messages[index])
    }

    /// Convert the opaque `JSONValue` payload from `block_start` into a typed
    /// `Block`. Failure logs in DEBUG and returns `nil` — a malformed block
    /// shouldn't tear down the whole turn.
    private func decodeBlock(from value: JSONValue) -> Block? {
        do {
            let data = try encoder.encode(value)
            return try blockDecoder.decode(Block.self, from: data)
        } catch {
            #if DEBUG
            Self.logger.error("block_start payload decode failed: \(String(describing: error), privacy: .public)")
            #endif
            return nil
        }
    }

    /// Apply a `block_data` patch to an existing block. Semantics are last-
    /// write-wins per top-level key (per the wire contract): re-encode the
    /// current block to a JSON dict, overlay the patch's keys, and re-decode
    /// as a `Block`. Non-object patches are ignored — the wire schema treats
    /// `data` as a partial object and any other shape is malformed.
    private func mergePatch(into block: Block, patch: JSONValue) -> Block? {
        guard case .object(let patchObject) = patch else {
            Self.logger.error("block_data patch was not a JSON object — ignoring")
            return nil
        }
        do {
            let currentData = try encoder.encode(block)
            let currentValue = try blockDecoder.decode(JSONValue.self, from: currentData)
            guard case .object(var currentObject) = currentValue else {
                return nil
            }
            for (key, value) in patchObject {
                currentObject[key] = value
            }
            let mergedData = try encoder.encode(JSONValue.object(currentObject))
            return try blockDecoder.decode(Block.self, from: mergedData)
        } catch {
            #if DEBUG
            Self.logger.error("block_data merge failed: \(String(describing: error), privacy: .public)")
            #endif
            return nil
        }
    }

    private func buildRequest(
        message: String,
        context: [String: JSONValue]?,
        idempotencyKey: String
    ) throws -> URLRequest {
        let path = "/v1/conversations/\(conversationId.uuidString.lowercased())/turns"
        guard let url = URL(string: baseURL + path) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body = TurnRequestBody(
            message: message,
            context: context,
            idempotencyKey: idempotencyKey,
            clientTimezone: timeZoneIdentifierProvider()
        )
        request.httpBody = try requestEncoder.encode(body)
        return request
    }

    private func buildActionRequest(
        actionId: String, decision: String
    ) throws -> URLRequest {
        let path =
            "/v1/conversations/\(conversationId.uuidString.lowercased())"
            + "/actions/\(actionId)"
        guard let url = URL(string: baseURL + path) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try requestEncoder.encode(
            ActionDecisionBody(decision: decision)
        )
        return request
    }
}

/// Wire body for `POST /v1/conversations/{id}/turns`. Mirrors
/// `app/schemas/conversations.py:ChatTurnRequest`. Digest cards ride `context`
/// as `kind=digest` (SEV-615 B), so there is no separate `digest_card` field.
private struct TurnRequestBody: Encodable {
    let message: String
    let context: [String: JSONValue]?
    let idempotencyKey: String
    let clientTimezone: String?

    private enum CodingKeys: String, CodingKey {
        case message
        case context
        case idempotencyKey = "idempotency_key"
        case clientTimezone = "client_timezone"
    }
}

/// Wire body for `POST /v1/conversations/{id}/actions/{actionId}`. Mirrors
/// `app/schemas/conversations.py:ActionDecisionRequest`. The client sends only
/// the decision — never the action's parameters.
private struct ActionDecisionBody: Encodable {
    let decision: String
}
