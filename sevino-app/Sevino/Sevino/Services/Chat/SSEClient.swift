import Foundation

/**
 A wire-level SSE event: the three fields the SSE spec promotes to
 protocol-level metadata (`id`, `event`) plus the joined `data` payload.

 `RawSSEEvent` is intentionally untyped — keeping the parser schema-agnostic
 means the SSE wire layer can be tested without depending on the chat event
 types, and it stays useful if we ever stream a different event flavour over
 the same transport.
 */
struct RawSSEEvent: Equatable, Sendable {
    /// Value of the `id:` line, or `nil` if the event had no `id:` field
    /// (the SSE spec allows events without one).
    let id: String?
    /// Value of the `event:` line — names the typed variant the JSON
    /// payload decodes to. Optional because the SSE spec allows events
    /// without an explicit type (defaulting to `"message"`).
    let event: String?
    /// Concatenated `data:` lines, joined with `\n` per the SSE spec.
    let data: String
}

/**
 Stateful parser that turns a stream of bytes into `RawSSEEvent` values.

 Why a custom byte-level parser instead of `URLSession.AsyncBytes.lines`:
 line boundaries and event boundaries can fall on any byte, including
 inside a single TCP segment. The parser keeps a small scratch buffer for
 the partial line at the tail of each chunk so events that arrive split
 across `read` boundaries are reassembled correctly.

 The parser is a value type with no I/O dependency so tests can drive it
 with arbitrarily-fragmented `Data` chunks; the `SSEClient` actor just
 owns the byte source and forwards.
 */
struct SSEParser: Sendable {
    private var buffer = Data()

    private var pendingId: String?
    private var pendingEvent: String?
    private var pendingData: [String] = []
    private var hasAnyField = false

    /**
     Feeds the next chunk of bytes from the network. Returns every event
     whose terminating empty line was contained in the combined buffer.
     Bytes that do not yet form a complete line are retained for the next
     call — feeding the same total bytes in one call or split across many
     produces the same events.
     */
    mutating func feed(_ chunk: Data) -> [RawSSEEvent] {
        buffer.append(chunk)
        var events: [RawSSEEvent] = []

        while let newlineIndex = buffer.firstIndex(of: 0x0A /* \n */) {
            let lineStart = buffer.startIndex
            // Strip trailing CR for CRLF tolerance — the SSE spec accepts
            // \n, \r\n, or \r as line terminators; servers using \r-only
            // are vanishingly rare so we do not handle them here, but CRLF
            // shows up whenever a proxy normalises line endings.
            let lineEnd: Data.Index
            if newlineIndex > lineStart, buffer[buffer.index(before: newlineIndex)] == 0x0D /* \r */ {
                lineEnd = buffer.index(before: newlineIndex)
            } else {
                lineEnd = newlineIndex
            }

            let lineData = buffer[lineStart..<lineEnd]
            let line = String(decoding: lineData, as: UTF8.self)
            if let event = handle(line: line) {
                events.append(event)
            }

            buffer.removeSubrange(lineStart...newlineIndex)
        }

        return events
    }

    private mutating func handle(line: String) -> RawSSEEvent? {
        if line.isEmpty {
            return dispatch()
        }
        // Lines starting with `:` are SSE comments — the spec uses these for
        // keep-alives. Drop without affecting in-flight event state.
        if line.hasPrefix(":") {
            return nil
        }

        let (field, value) = Self.split(line: line)
        switch field {
        case "id":
            pendingId = value
            hasAnyField = true
        case "event":
            pendingEvent = value
            hasAnyField = true
        case "data":
            pendingData.append(value)
            hasAnyField = true
        case "retry":
            // Explicit case acknowledges the SSE spec field; reconnect
            // timing is not yet honoured. The spec requires us to silently
            // drop unknown fields, which the default branch also does.
            break
        default:
            break
        }
        return nil
    }

    private mutating func dispatch() -> RawSSEEvent? {
        defer {
            pendingId = nil
            pendingEvent = nil
            pendingData = []
            hasAnyField = false
        }
        guard hasAnyField else {
            // Empty line with no preceding fields — keep-alive separator.
            return nil
        }
        return RawSSEEvent(
            id: pendingId,
            event: pendingEvent,
            data: pendingData.joined(separator: "\n")
        )
    }

    /// Splits a line into its `(field, value)` pair per the SSE spec: the
    /// field name runs up to the first colon; the value is everything after,
    /// with at most a single leading space stripped (so both `data:foo` and
    /// `data: foo` yield `foo`). A line with no colon is a field-only line
    /// with an empty value.
    private static func split(line: String) -> (String, String) {
        guard let colon = line.firstIndex(of: ":") else {
            return (line, "")
        }
        let field = String(line[line.startIndex..<colon])
        var valueStart = line.index(after: colon)
        if valueStart < line.endIndex, line[valueStart] == " " {
            valueStart = line.index(after: valueStart)
        }
        return (field, String(line[valueStart..<line.endIndex]))
    }
}

/// Errors raised by `SSEClient` while opening a stream. Decode errors of
/// individual SSE payloads are not modelled here — the wire layer is
/// schema-agnostic.
enum SSEClientError: Error, Equatable {
    /// Server returned a non-2xx response when we tried to open the stream.
    case httpStatus(Int)
}

/**
 Streams SSE events from an HTTP endpoint.

 The actor owns a `URLSession` and an auth token provider; each call to
 `stream(request:)` opens an independent `URLSession.bytes(for:)` connection,
 feeds the bytes through `SSEParser`, and yields parsed events on an
 `AsyncThrowingStream`. The client attaches `Accept: text/event-stream`,
 `X-API-Key`, and `Authorization: Bearer <token>` automatically — callers
 just supply the request URL/method/body.

 Auth headers are resolved per-stream rather than baked in at construction
 time so that a future reconnect path picks up a freshly-refreshed JWT
 without needing a new `SSEClient` instance.

 The class is an actor (rather than a final class) so future state — open
 stream tracking, retry budget, last-event-id store — can be added without
 changing the call site signature.
 */
actor SSEClient {
    /// Provides the OAuth bearer token to attach to each opened stream.
    /// Returning `nil` skips the `Authorization` header — useful in tests
    /// and for pre-auth probes; unauthenticated calls to the chat endpoint
    /// will be rejected by the server.
    typealias TokenProvider = @Sendable () async -> String?

    private let session: URLSession
    private let tokenProvider: TokenProvider
    private let apiKey: String

    init(
        session: URLSession = .shared,
        tokenProvider: @escaping TokenProvider = {
            await (AuthService.shared as AuthServiceProtocol).accessToken
        },
        apiKey: String = AppConfig.apiKey
    ) {
        self.session = session
        self.tokenProvider = tokenProvider
        self.apiKey = apiKey
    }

    /**
     Opens an SSE connection for `request` and returns a stream of parsed
     events. The returned stream:

     - throws `SSEClientError.httpStatus(_:)` if the server responds with a
       non-2xx status — the body is consumed but not surfaced;
     - finishes normally when the server closes the connection;
     - cancels the underlying `URLSession.bytes(for:)` task if the consumer
       breaks out of its `for await` early or the stream's continuation is
       terminated.

     `nonisolated` so callers can synchronously create the stream and
     subscribe in one expression — the stream's work runs in a `Task`
     hopped onto the actor.
     */
    nonisolated func stream(request: URLRequest) -> AsyncThrowingStream<RawSSEEvent, any Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                await self.consume(request: request, continuation: continuation)
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    private func consume(
        request: URLRequest,
        continuation: AsyncThrowingStream<RawSSEEvent, any Error>.Continuation
    ) async {
        do {
            var augmented = request
            augmented.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            if !apiKey.isEmpty {
                augmented.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
            }
            if let token = await tokenProvider() {
                augmented.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }

            let (bytes, response) = try await session.bytes(for: augmented)
            try Task.checkCancellation()

            if let http = response as? HTTPURLResponse,
               !(200..<300).contains(http.statusCode) {
                continuation.finish(throwing: SSEClientError.httpStatus(http.statusCode))
                return
            }

            var parser = SSEParser()
            // Buffer bytes between newlines so we don't pay the parser
            // dispatch cost per byte — `URLSession.AsyncBytes` yields
            // one `UInt8` per iteration.
            var pending = Data()
            pending.reserveCapacity(4096)
            for try await byte in bytes {
                pending.append(byte)
                if byte == 0x0A {
                    for event in parser.feed(pending) {
                        continuation.yield(event)
                    }
                    pending.removeAll(keepingCapacity: true)
                }
            }
            // Tail flush — feed any trailing bytes (last frame without a
            // terminating newline). The parser's empty-line-required rule
            // means an event without `\n\n` is dropped, matching the spec.
            if !pending.isEmpty {
                for event in parser.feed(pending) {
                    continuation.yield(event)
                }
            }

            continuation.finish()
        } catch is CancellationError {
            continuation.finish()
        } catch {
            continuation.finish(throwing: error)
        }
    }
}
