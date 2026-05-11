import Foundation
@testable import Sevino

/**
 Test-only `SSEClientProtocol` implementation that yields a scripted timeline
 of events.

 Lives in the test target. If a SwiftUI preview ever needs a fake SSE stream
 (likely when SEV-510 / SEV-511 wires the message list into HomeView), add a
 small preview-only factory in the production target — guarded with
 `#if DEBUG` — at that point rather than promoting this mock. Keeping the
 test mock test-only avoids shipping any test scaffolding in the release
 binary.

 The type is `@unchecked Sendable` and uses an internal lock to record
 captured requests; all other state is immutable after construction.

 Usage:
 ```swift
 let client = MockSSEClient(script: [
     .yield(makeRaw(type: "turn_started", payload: ...)),
     .yield(makeRaw(type: "block_start", payload: ...)),
     .yield(makeRaw(type: "turn_completed", payload: ...)),
 ])
 let store = ConversationStore(sseClient: client, ...)
 try await store.send(text: "hi")
 ```
 */
final class MockSSEClient: SSEClientProtocol, @unchecked Sendable {

    /// One step in the scripted timeline. The script is replayed in order,
    /// once per `stream(request:)` call.
    enum Step: Sendable {
        /// Emit a raw SSE event to the consumer.
        case yield(RawSSEEvent)
        /// Finish the stream by throwing — simulates a transport failure or
        /// a non-2xx HTTP response surfacing as `SSEClientError.httpStatus`.
        case fail(any Error)
        /// Park until the consumer cancels the underlying task before
        /// finishing — used to test cancellation cleanup.
        case awaitCancellation
    }

    private let scripts: [[Step]]
    private let lock = NSLock()
    private var _capturedRequests: [URLRequest] = []
    private var _streamCallIndex = 0

    /// Every `URLRequest` the store has handed off to this mock, in call order.
    /// Tests use this to assert URL, method, and body shape.
    var capturedRequests: [URLRequest] {
        lock.lock()
        defer { lock.unlock() }
        return _capturedRequests
    }

    /// Single-script init: every `stream(request:)` call replays the same script.
    init(script: [Step] = []) {
        self.scripts = [script]
    }

    /// Multi-script init: the Nth call to `stream(request:)` replays
    /// `scripts[N]`. Callers exceeding the script count get an empty stream
    /// that finishes immediately (no events). Used to cover sequential
    /// `send(text:)` calls on the same store.
    init(scripts: [[Step]]) {
        self.scripts = scripts
    }

    // `SSEClient.stream(_:)` is `nonisolated` so callers from any actor can
    // synchronously open the stream; this mock matches that contract.
    nonisolated func stream(request: URLRequest) -> AsyncThrowingStream<RawSSEEvent, any Error> {
        lock.lock()
        _capturedRequests.append(request)
        let index = _streamCallIndex
        _streamCallIndex += 1
        lock.unlock()

        let script = scripts.indices.contains(index) ? scripts[index] : []
        return AsyncThrowingStream { continuation in
            let task = Task {
                for step in script {
                    if Task.isCancelled {
                        continuation.finish()
                        return
                    }
                    switch step {
                    case .yield(let event):
                        continuation.yield(event)
                        // Cooperative yield so the consumer's actor (the
                        // `@MainActor` ConversationStore) gets a chance to
                        // run between events — otherwise the whole script
                        // executes in one continuation and tests can't
                        // observe intermediate state.
                        await Task.yield()
                    case .fail(let error):
                        continuation.finish(throwing: error)
                        return
                    case .awaitCancellation:
                        while !Task.isCancelled {
                            do {
                                try await Task.sleep(for: .milliseconds(5))
                            } catch {
                                break
                            }
                        }
                        continuation.finish()
                        return
                    }
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

extension MockSSEClient {
    /// Convenience builder for a `RawSSEEvent` carrying a JSON string payload.
    /// Defaults match the wire-format defaults (`event` line set to the JSON
    /// `type` discriminator is conventional but not required by `SSEEvent`'s
    /// own dispatch — the typed decoder reads the JSON `type` field).
    static func makeRaw(id: String = "01TEST", event: String? = nil, json: String) -> RawSSEEvent {
        RawSSEEvent(id: id, event: event, data: json)
    }
}
