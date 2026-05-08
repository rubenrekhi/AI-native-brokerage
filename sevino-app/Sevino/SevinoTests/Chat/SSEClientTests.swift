import XCTest
@testable import Sevino

final class SSEParserTests: XCTestCase {

    // MARK: - Single-frame parsing

    func testSingleEventWithAllThreeFields() {
        var parser = SSEParser()
        let frame = Data("id: 01ABC\nevent: text_delta\ndata: {\"text\":\"hi\"}\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [
            RawSSEEvent(id: "01ABC", event: "text_delta", data: "{\"text\":\"hi\"}")
        ])
    }

    func testEventWithoutIdOrEventLineParsesData() {
        // SSE allows omitting both id and event — the spec defaults event to
        // "message". We surface them as nil and let the next layer decide.
        var parser = SSEParser()
        let frame = Data("data: hello\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: nil, data: "hello")])
    }

    func testMultipleDataLinesAreJoinedWithNewline() {
        var parser = SSEParser()
        let frame = Data("data: line one\ndata: line two\ndata: line three\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(
            events,
            [RawSSEEvent(id: nil, event: nil, data: "line one\nline two\nline three")]
        )
    }

    func testValueWithoutLeadingSpaceIsAccepted() {
        // "data:foo" should yield "foo" — only ONE leading space is stripped,
        // and absent space means the value starts immediately after the colon.
        var parser = SSEParser()
        let frame = Data("data:foo\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: nil, data: "foo")])
    }

    func testValueRetainsAdditionalLeadingSpaces() {
        // Per spec, only one leading space is stripped — preserve the second.
        var parser = SSEParser()
        let frame = Data("data:  doubled\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: nil, data: " doubled")])
    }

    func testCommentLinesAreIgnored() {
        var parser = SSEParser()
        let frame = Data(": this is a heartbeat comment\ndata: real\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: nil, data: "real")])
    }

    func testStandaloneEmptyLineWithoutFieldsEmitsNothing() {
        // Keep-alive frames consist of nothing but blank lines — they must
        // not generate phantom RawSSEEvent values.
        var parser = SSEParser()
        let frame = Data("\n\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertTrue(events.isEmpty)
    }

    func testRetryFieldIsAcceptedButDropped() {
        // The parser must tolerate `retry:` lines without leaking them
        // into an event — reconnect timing is not yet honoured.
        var parser = SSEParser()
        let frame = Data("retry: 3000\ndata: payload\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: nil, data: "payload")])
    }

    func testUnknownFieldsAreSilentlyDropped() {
        var parser = SSEParser()
        let frame = Data("foo: bar\ndata: payload\n\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: nil, data: "payload")])
    }

    // MARK: - CRLF tolerance

    func testCRLFLineEndingsAreSupported() {
        // Some proxies normalise to CRLF; the parser must strip the trailing
        // CR before promoting the line to a value.
        var parser = SSEParser()
        let frame = Data("event: status\r\ndata: ok\r\n\r\n".utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [RawSSEEvent(id: nil, event: "status", data: "ok")])
    }

    // MARK: - Multiple events in one feed

    func testMultipleEventsInOneFeedAreSeparated() {
        var parser = SSEParser()
        let frame = Data("""
        id: 1
        event: turn_started
        data: {"turn_id":"a"}

        id: 2
        event: turn_completed
        data: {"turn_id":"a"}


        """.utf8)

        let events = parser.feed(frame)

        XCTAssertEqual(events, [
            RawSSEEvent(id: "1", event: "turn_started", data: "{\"turn_id\":\"a\"}"),
            RawSSEEvent(id: "2", event: "turn_completed", data: "{\"turn_id\":\"a\"}"),
        ])
    }

    // MARK: - Cross-boundary feeds

    func testEventSplitAcrossFeedsIsReassembled() {
        // The same total bytes — split at every conceivable boundary — must
        // yield identical events: events split across `read` boundaries are
        // recovered.
        let wholeFrame = Data("id: 01\nevent: text_delta\ndata: hi\n\n".utf8)

        for splitIndex in 1..<wholeFrame.count {
            var parser = SSEParser()
            let head = wholeFrame.prefix(splitIndex)
            let tail = wholeFrame.suffix(from: splitIndex)
            let firstFeed = parser.feed(head)
            let secondFeed = parser.feed(tail)

            let combined = firstFeed + secondFeed
            XCTAssertEqual(
                combined,
                [RawSSEEvent(id: "01", event: "text_delta", data: "hi")],
                "split at byte \(splitIndex) lost or duplicated the event"
            )
        }
    }

    func testMultipleEventsSplitAtEveryBoundary() {
        // Two-event stream: ensure the second event survives a split that
        // lands inside it (regression guard for buffer state between dispatches).
        let stream = Data("""
        id: 1
        data: a

        id: 2
        data: b


        """.utf8)

        for splitIndex in 1..<stream.count {
            var parser = SSEParser()
            let head = stream.prefix(splitIndex)
            let tail = stream.suffix(from: splitIndex)
            let combined = parser.feed(head) + parser.feed(tail)
            XCTAssertEqual(
                combined,
                [
                    RawSSEEvent(id: "1", event: nil, data: "a"),
                    RawSSEEvent(id: "2", event: nil, data: "b"),
                ],
                "split at byte \(splitIndex) corrupted the two-event stream"
            )
        }
    }

    func testByteByByteFeedYieldsSameEvents() {
        // Worst-case fragmentation: feed one byte at a time. Tests that the
        // partial-line buffer survives every possible boundary.
        let stream = Data("event: status\ndata: streaming\n\nevent: status\ndata: done\n\n".utf8)
        var parser = SSEParser()
        var events: [RawSSEEvent] = []
        for byte in stream {
            events.append(contentsOf: parser.feed(Data([byte])))
        }

        XCTAssertEqual(events, [
            RawSSEEvent(id: nil, event: "status", data: "streaming"),
            RawSSEEvent(id: nil, event: "status", data: "done"),
        ])
    }

    // MARK: - Trailing partial frames

    func testTrailingFrameWithoutTerminatorIsHeld() {
        // A frame that hasn't received its closing empty line must NOT be
        // emitted — otherwise we'd surface incomplete events to the caller.
        var parser = SSEParser()
        let partial = Data("id: 1\ndata: partial".utf8)

        let events = parser.feed(partial)

        XCTAssertTrue(events.isEmpty)
    }

    func testHeldPartialFrameCompletesOnNextFeed() {
        var parser = SSEParser()
        _ = parser.feed(Data("id: 1\ndata: par".utf8))
        let events = parser.feed(Data("tial\n\n".utf8))

        XCTAssertEqual(events, [RawSSEEvent(id: "1", event: nil, data: "partial")])
    }
}

@MainActor
final class SSEClientTests: XCTestCase {

    private var session: URLSession!

    override func setUp() {
        super.setUp()
        session = StubURLProtocol.makeSession()
    }

    override func tearDown() {
        StubURLProtocol.reset()
        session = nil
        super.tearDown()
    }

    // MARK: - End-to-end happy path

    func testStreamYieldsParsedEventsForA200Response() async throws {
        let body = Data("""
        id: 01
        event: turn_started
        data: {"turn_id":"abc"}

        id: 02
        event: text_delta
        data: hello


        """.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(
                status: 200,
                body: body,
                headers: ["Content-Type": "text/event-stream"]
            )
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        var events: [RawSSEEvent] = []
        for try await event in client.stream(request: request) {
            events.append(event)
        }

        XCTAssertEqual(events, [
            RawSSEEvent(id: "01", event: "turn_started", data: "{\"turn_id\":\"abc\"}"),
            RawSSEEvent(id: "02", event: "text_delta", data: "hello"),
        ])
    }

    // MARK: - HTTP error handling

    func testNon2xxResponseSurfacesAsHTTPStatusError() async {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 401, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        do {
            for try await _ in client.stream(request: request) {
                XCTFail("expected stream to throw before yielding")
            }
            XCTFail("expected stream to throw")
        } catch let error as SSEClientError {
            XCTAssertEqual(error, .httpStatus(401))
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testTransportErrorIsForwardedToStream() async {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .failure(URLError(.notConnectedToInternet))
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        do {
            for try await _ in client.stream(request: request) {
                XCTFail("expected transport error to surface")
            }
            XCTFail("expected stream to throw")
        } catch let error as URLError {
            XCTAssertEqual(error.code, .notConnectedToInternet)
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - Header injection

    func testAcceptHeaderIsAlwaysAttached() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        for try await _ in client.stream(request: request) {}

        XCTAssertEqual(
            StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "Accept"),
            "text/event-stream"
        )
    }

    func testAuthorizationHeaderUsesTokenProvider() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { "fake-jwt" }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        for try await _ in client.stream(request: request) {}

        XCTAssertEqual(
            StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "Authorization"),
            "Bearer fake-jwt"
        )
    }

    func testAuthorizationHeaderOmittedWhenTokenNil() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        for try await _ in client.stream(request: request) {}

        XCTAssertNil(StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "Authorization"))
    }

    func testAPIKeyHeaderAttachedWhenConfigured() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "secret-key")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        for try await _ in client.stream(request: request) {}

        XCTAssertEqual(
            StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "X-API-Key"),
            "secret-key"
        )
    }

    func testAPIKeyHeaderOmittedWhenEmpty() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        for try await _ in client.stream(request: request) {}

        XCTAssertNil(StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "X-API-Key"))
    }

    // MARK: - Early termination

    func testEarlyBreakLeavesActorReusable() async throws {
        // Pins the documented contract that breaking out of `for try await`
        // tears down the underlying task via `continuation.onTermination`
        // without leaking or hanging — verified by reusing the same client
        // for a second stream that completes normally.
        let firstBody = Data("""
        id: 1
        data: a

        id: 2
        data: b

        id: 3
        data: c


        """.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: firstBody)
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        let request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)

        var firstID: String?
        for try await event in client.stream(request: request) {
            firstID = event.id
            break
        }
        XCTAssertEqual(firstID, "1")

        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data("data: ok\n\n".utf8))
        )
        var secondEvents: [RawSSEEvent] = []
        for try await event in client.stream(request: request) {
            secondEvents.append(event)
        }
        XCTAssertEqual(secondEvents, [RawSSEEvent(id: nil, event: nil, data: "ok")])
    }

    func testCallerSuppliedHeadersArePreserved() async throws {
        // The client should add its own headers without clobbering anything
        // the caller already set on the URLRequest (e.g. Idempotency-Key).
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/turns",
            response: .success(status: 200, body: Data())
        )

        let client = SSEClient(session: session, tokenProvider: { nil }, apiKey: "")
        var request = URLRequest(url: URL(string: "https://api.example.com/v1/turns")!)
        request.setValue("idem-123", forHTTPHeaderField: "Idempotency-Key")

        for try await _ in client.stream(request: request) {}

        XCTAssertEqual(
            StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "Idempotency-Key"),
            "idem-123"
        )
    }
}
