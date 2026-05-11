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
    private let conversationId: UUID
    private let baseURL: String
    private let idempotencyKeyFactory: @Sendable () -> String

    /// Default `JSONDecoder` for `SSEEvent`. The event payload structs declare
    /// explicit `CodingKeys` (e.g. `turnId = "turn_id"`) that *only* match
    /// when the decoder leaves JSON keys untouched — `convertFromSnakeCase`
    /// would transform `turn_id` to `turnId` before lookup and miss the
    /// explicit mapping. Locked to a property to match the strategy used in
    /// `SSEEventTests`.
    private let eventDecoder = JSONDecoder()
    /// `Block` and the request body rely on the project-wide snake_case ↔
    /// camelCase strategy (see `JSONCoders+Sevino.swift`). Used to round-trip
    /// `block_start` / `block_data` payloads from `JSONValue` into typed
    /// blocks and to encode `TurnRequestBody`.
    private let blockDecoder = JSONDecoder.sevino()
    private let encoder = JSONEncoder.sevino()

    /// id of the assistant `Message` currently being populated by SSE events,
    /// or `nil` between turns. Stored separately from `messages.last?.id` so a
    /// stray pre-`turn_started` event can't accidentally mutate the user's
    /// optimistic message.
    private var currentAssistantMessageId: UUID?

    private static let logger = Logger(subsystem: "ai.sevino.Sevino", category: "ConversationStore")

    init(
        conversationId: UUID = UUID(),
        sseClient: any SSEClientProtocol = SSEClient(),
        baseURL: String = AppConfig.apiBaseURL,
        idempotencyKeyFactory: @escaping @Sendable () -> String = { UUID().uuidString }
    ) {
        self.conversationId = conversationId
        self.sseClient = sseClient
        self.baseURL = baseURL
        self.idempotencyKeyFactory = idempotencyKeyFactory
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
    func send(text: String, idempotencyKey: String? = nil) async throws {
        let userMessage = Message(
            id: UUID(),
            role: .user,
            blocks: [.text(TextBlock(blockId: UUID().uuidString, text: text))]
        )
        messages.append(userMessage)

        let request = try buildRequest(
            message: text,
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

    private func apply(_ event: SSEEvent) {
        switch event {
        case .turnStarted(let payload):
            currentTurnId = payload.turnId
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
                guard let index = message.blocks.firstIndex(where: { $0.blockId == payload.blockId }),
                      case .text(let block) = message.blocks[index] else {
                    Self.logger.error("text_delta references unknown text block id")
                    return
                }
                message.blocks[index] = .text(
                    TextBlock(blockId: block.blockId, text: block.text + payload.text)
                )
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

    private func buildRequest(message: String, idempotencyKey: String) throws -> URLRequest {
        let path = "/v1/conversations/\(conversationId.uuidString.lowercased())/turns"
        guard let url = URL(string: baseURL + path) else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body = TurnRequestBody(message: message, idempotencyKey: idempotencyKey)
        request.httpBody = try encoder.encode(body)
        return request
    }
}

/// Wire body for `POST /v1/conversations/{id}/turns`. Mirrors
/// `app/schemas/conversations.py:ChatTurnRequest`. Lives here (not in
/// `Models/`) because it has no consumers outside the store and the wire
/// shape is one-line trivial.
private struct TurnRequestBody: Encodable {
    let message: String
    let idempotencyKey: String
}
