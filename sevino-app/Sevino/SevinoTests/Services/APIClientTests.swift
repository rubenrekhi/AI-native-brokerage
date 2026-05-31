import XCTest
@testable import Sevino

final class APIClientTests: XCTestCase {

    private var session: URLSession!

    private struct Payload: Codable, Equatable {
        let message: String
    }

    override func setUp() {
        super.setUp()
        session = StubURLProtocol.makeSession()
    }

    override func tearDown() {
        StubURLProtocol.reset()
        session = nil
        super.tearDown()
    }

    // MARK: - Success

    func testGetDecodesJSONBody() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/hello",
            response: .success(status: 200, body: Data(#"{"message":"hi"}"#.utf8))
        )

        let client = makeClient()
        let body: Payload = try await client.get("/v1/hello")

        XCTAssertEqual(body, Payload(message: "hi"))
        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
    }

    func testPostAttachesJSONBody() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/echo",
            response: .success(status: 200, body: Data(#"{"message":"ok"}"#.utf8))
        )

        let client = makeClient()
        let _: Payload = try await client.post("/v1/echo", body: Payload(message: "ping"))

        let sent = StubURLProtocol.lastRequest()
        XCTAssertEqual(sent?.httpMethod, "POST")
        XCTAssertEqual(sent?.value(forHTTPHeaderField: "Content-Type"), "application/json")
        // URLProtocol drops httpBody — read from httpBodyStream.
        let bodyData = sent?.httpBodyStream.flatMap { readAll($0) }
        XCTAssertEqual(bodyData, Data(#"{"message":"ping"}"#.utf8))
    }

    func testEncoderConvertsCamelCaseToSnakeCase() async throws {
        struct Request: Encodable { let preferredName: String }
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/profile",
            response: .success(status: 200, body: Data(#"{"message":"ok"}"#.utf8))
        )

        let client = makeClient()
        let _: Payload = try await client.post("/v1/profile", body: Request(preferredName: "Riley"))

        let bodyData = StubURLProtocol.lastRequest()?.httpBodyStream.flatMap { readAll($0) }
        XCTAssertEqual(bodyData, Data(#"{"preferred_name":"Riley"}"#.utf8))
    }

    func testDecoderConvertsSnakeCaseToCamelCase() async throws {
        struct Response: Decodable, Equatable { let preferredName: String }
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/profile",
            response: .success(status: 200, body: Data(#"{"preferred_name":"Riley"}"#.utf8))
        )

        let client = makeClient()
        let body: Response = try await client.get("/v1/profile")

        XCTAssertEqual(body, Response(preferredName: "Riley"))
    }

    func testGetTodaysDigestReturnsNilOn204() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/digest/today",
            response: .success(status: 204, body: Data())
        )

        let client = makeClient()
        let body = try await client.getTodaysDigest()

        XCTAssertNil(body)
        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
    }

    func testDismissDigestPostsToDigestDismiss() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/digest/dismiss",
            response: .success(status: 204, body: Data())
        )

        let client = makeClient()
        try await client.dismissDigest()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "POST")
    }

    // MARK: - Headers

    func testAuthorizationHeaderAttachedWhenTokenAvailable() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/me",
            response: .success(status: 200, body: Data(#"{"message":"ok"}"#.utf8))
        )

        let client = makeClient(token: "fake-jwt")
        let _: Payload = try await client.get("/v1/me")

        XCTAssertEqual(
            StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "Authorization"),
            "Bearer fake-jwt"
        )
    }

    func testAuthorizationHeaderOmittedWhenTokenNil() async throws {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/me",
            response: .success(status: 200, body: Data(#"{"message":"ok"}"#.utf8))
        )

        let client = makeClient(token: nil)
        let _: Payload = try await client.get("/v1/me")

        XCTAssertNil(StubURLProtocol.lastRequest()?.value(forHTTPHeaderField: "Authorization"))
    }

    // MARK: - Errors

    func testDecodableAPIErrorIsThrown() async {
        let errorBody = Data(#"{"error":"Not found","code":"NOT_FOUND"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/missing",
            response: .success(status: 404, body: errorBody)
        )

        let client = makeClient()

        do {
            let _: Payload = try await client.get("/v1/missing")
            XCTFail("expected APIError to be thrown")
        } catch let error as APIError {
            XCTAssertEqual(error.code, APIError.Code.notFound)
            XCTAssertEqual(error.error, "Not found")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testNonDecodableErrorBodyFallsBackToUnknown() async {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/boom",
            response: .success(status: 500, body: Data("plain text".utf8))
        )

        let client = makeClient()

        do {
            let _: Payload = try await client.get("/v1/boom")
            XCTFail("expected APIError.unknown to be thrown")
        } catch let error as APIError {
            XCTAssertEqual(error.code, APIError.Code.unknown)
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - Helpers

    private func makeClient(token: String? = nil) -> APIClient {
        APIClient(
            baseURL: "https://api.example.com",
            session: session,
            tokenProvider: { token }
        )
    }

    private func readAll(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: 1024)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }
}
