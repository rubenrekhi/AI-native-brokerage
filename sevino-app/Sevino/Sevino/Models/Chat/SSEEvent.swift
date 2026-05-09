import Foundation
import os.log

/**
 Typed SSE event from the chat-turn endpoint.

 Hand-mirrors the eight-variant Pydantic discriminated union in
 `sevino-api/app/ai/transport/events.py:Event`. There is no codegen and no
 CI check — drift between the two breaks the iOS decoder at runtime. When
 either side adds, removes, or renames a variant, the matching change MUST
 land in the same PR (see the "AI wire format" section in the root
 `CLAUDE.md`).

 The associated payloads use field names matching the Swift convention
 (`turnId`, `blockId`, …); the wire JSON uses snake_case and is mapped via
 `CodingKeys` per struct.

 The `block` payload on `block_start` and the `data` payload on `block_data`
 are kept opaque (`JSONValue`) — the typed `Block` enum lands in C3.3 and
 will replace these fields once available.
 */
enum SSEEvent: Equatable, Sendable {
    case turnStarted(TurnStarted)
    case status(Status)
    case blockStart(BlockStart)
    case textDelta(TextDelta)
    case blockData(BlockData)
    case blockEnd(BlockEnd)
    case turnCompleted(TurnCompleted)
    case error(ErrorEvent)
}

extension SSEEvent {
    /// First frame of every turn. Carries the IDs the client uses to correlate
    /// the stream back to the assistant message and conversation rows.
    struct TurnStarted: Decodable, Equatable, Sendable {
        let id: String
        let turnId: UUID
        let conversationId: UUID

        private enum CodingKeys: String, CodingKey {
            case id
            case turnId = "turn_id"
            case conversationId = "conversation_id"
        }
    }

    /// Turn-level status note that is NOT bound to a block. Status pills in v0
    /// are rendered from `StatusBlock` blocks (carried on `blockStart` /
    /// `blockEnd`); this event is reserved for transient progress text outside
    /// the block model.
    struct Status: Decodable, Equatable, Sendable {
        let id: String
        let label: String
    }

    /// A new content block has begun streaming. `block` is the initial block
    /// payload — its own `block_id` field is what subsequent `textDelta` /
    /// `blockData` / `blockEnd` events reference.
    struct BlockStart: Decodable, Equatable, Sendable {
        let id: String
        let block: JSONValue
    }

    /// Append text to an open `text` block.
    struct TextDelta: Decodable, Equatable, Sendable {
        let id: String
        let blockId: String
        let text: String

        private enum CodingKeys: String, CodingKey {
            case id, text
            case blockId = "block_id"
        }
    }

    /// Partial JSON patch to an open block. Clients merge `data` into the
    /// block by field; semantics are last-write-wins per key.
    struct BlockData: Decodable, Equatable, Sendable {
        let id: String
        let blockId: String
        let data: JSONValue

        private enum CodingKeys: String, CodingKey {
            case id, data
            case blockId = "block_id"
        }
    }

    /// Marks an open block as finished — no further deltas for `blockId`.
    struct BlockEnd: Decodable, Equatable, Sendable {
        let id: String
        let blockId: String

        private enum CodingKeys: String, CodingKey {
            case id
            case blockId = "block_id"
        }
    }

    /// Successful terminal frame.
    struct TurnCompleted: Decodable, Equatable, Sendable {
        let id: String
        let turnId: UUID
        let terminalState: String
        let totalCostUsdMicros: Int
        let iterationsCount: Int

        private enum CodingKeys: String, CodingKey {
            case id
            case turnId = "turn_id"
            case terminalState = "terminal_state"
            case totalCostUsdMicros = "total_cost_usd_micros"
            case iterationsCount = "iterations_count"
        }
    }

    /// Error terminal frame. `code` is the closed taxonomy clients branch on;
    /// `message` is for human readers only and must never be load-bearing for
    /// client behaviour.
    struct ErrorEvent: Decodable, Equatable, Sendable {
        let id: String
        let code: ErrorCode
        let message: String?
    }

    /// Closed error taxonomy mirroring `app/ai/runtime/errors.py:ErrorCode`.
    /// `unknown` is the iOS-only safety valve: a value the backend ships
    /// before this enum is updated decodes to `.unknown` rather than failing
    /// the whole event — the rest of the frame is still useful (the human
    /// `message` will tell the user something went wrong).
    enum ErrorCode: String, Equatable, Sendable {
        case toolTimeout = "tool_timeout"
        case toolError = "tool_error"
        case modelOverloaded = "model_overloaded"
        case modelRateLimit = "model_rate_limit"
        case internalError = "internal_error"
        case cancelled
        case turnIterationLimit = "turn_iteration_limit"
        case toolCallLimit = "tool_call_limit"
        case outputTokenLimit = "output_token_limit"
        case validationError = "validation_error"
        case unknown
    }
}

extension SSEEvent.ErrorCode: Decodable {
    init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        self = SSEEvent.ErrorCode(rawValue: raw) ?? .unknown
    }
}

extension SSEEvent: Decodable {
    private enum DiscriminatorKey: String, CodingKey {
        case type
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: DiscriminatorKey.self)
        let type = try container.decode(String.self, forKey: .type)
        switch type {
        case "turn_started":
            self = .turnStarted(try TurnStarted(from: decoder))
        case "status":
            self = .status(try Status(from: decoder))
        case "block_start":
            self = .blockStart(try BlockStart(from: decoder))
        case "text_delta":
            self = .textDelta(try TextDelta(from: decoder))
        case "block_data":
            self = .blockData(try BlockData(from: decoder))
        case "block_end":
            self = .blockEnd(try BlockEnd(from: decoder))
        case "turn_completed":
            self = .turnCompleted(try TurnCompleted(from: decoder))
        case "error":
            self = .error(try ErrorEvent(from: decoder))
        default:
            // Strict discriminator: surface unknown variants loudly rather
            // than silently dropping the event. Backend taxonomy is closed,
            // so a value we don't recognise points at schema drift.
            throw DecodingError.dataCorruptedError(
                forKey: DiscriminatorKey.type,
                in: container,
                debugDescription: "Unknown SSE event type: \(type)"
            )
        }
    }
}

extension SSEEvent {
    /// The wire-level `type` discriminator for the receiver. Matches the value
    /// the backend writes to the SSE `event:` line and the JSON `type` field.
    var wireType: String {
        switch self {
        case .turnStarted:   "turn_started"
        case .status:        "status"
        case .blockStart:    "block_start"
        case .textDelta:     "text_delta"
        case .blockData:     "block_data"
        case .blockEnd:      "block_end"
        case .turnCompleted: "turn_completed"
        case .error:         "error"
        }
    }

    private static let logger = Logger(subsystem: "ai.sevino.Sevino", category: "SSEEvent")

    /// Decode an SSE event from the JSON payload of a `RawSSEEvent.data` field.
    ///
    /// In DEBUG builds, decode failures are logged via `os_log` — the structural
    /// error stays public (decoding-error type, missing key, etc.) but the raw
    /// payload is marked `.private` so it never reaches the unified log on
    /// non-DEBUG distributions (TestFlight via Staging, Release). Chat content
    /// includes message text, ticker watchlists, and tool I/O — none of which
    /// belong in `os_log`.
    static func decode(
        from data: Data,
        decoder: JSONDecoder = JSONDecoder()
    ) throws -> SSEEvent {
        do {
            return try decoder.decode(SSEEvent.self, from: data)
        } catch {
            #if DEBUG
            let payload = String(data: data, encoding: .utf8) ?? "<non-utf8 \(data.count) bytes>"
            logger.error(
                "SSE event decode failed: \(String(describing: error), privacy: .public). Payload: \(payload, privacy: .private)"
            )
            #endif
            throw error
        }
    }
}
