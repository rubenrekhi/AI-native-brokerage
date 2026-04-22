import XCTest
@testable import Sevino

final class HealthCheckServiceTests: XCTestCase {

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

    // MARK: - Backend

    func testBackendReachableSurfacesStatusFields() async {
        let body = #"{"status":"ok","db":"ok","redis":"ok"}"#.data(using: .utf8)!
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/health",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        let result = await service.check(.backend)

        XCTAssertTrue(result.reachable)
        XCTAssertEqual(result.statusCode, 200)
        XCTAssertEqual(result.details["status"], "ok")
        XCTAssertEqual(result.details["db"], "ok")
        XCTAssertEqual(result.details["redis"], "ok")
        XCTAssertNil(result.error)
    }

    func testBackendDegradedReportsUnreachableWith503() async {
        let body = #"{"status":"degraded","db":"error","redis":"ok"}"#.data(using: .utf8)!
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/health",
            response: .success(status: 503, body: body)
        )

        let service = makeService()
        let result = await service.check(.backend)

        XCTAssertFalse(result.reachable, "503 means backend is degraded — treat as unreachable so UI flags it")
        XCTAssertEqual(result.statusCode, 503)
        XCTAssertEqual(result.error, "HTTP 503")
        XCTAssertEqual(result.details["db"], "error")
    }

    func testBackendNetworkFailureIsSurfacedInError() async {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/health",
            response: .failure(URLError(.notConnectedToInternet))
        )

        let service = makeService()
        let result = await service.check(.backend)

        XCTAssertFalse(result.reachable)
        XCTAssertNotNil(result.error)
        XCTAssertNil(result.statusCode)
    }

    func testBackendEmptyBaseURLSurfacesConfigError() async {
        let service = HealthCheckService(
            apiBaseURL: "",
            supabaseURL: "https://sb.example.com",
            session: session,
            clock: { 0 }
        )

        let result = await service.check(.backend)

        XCTAssertFalse(result.reachable)
        XCTAssertEqual(result.error, "API base URL is not configured")
    }

    func testBackendLatencyIsComputedFromClock() async {
        let body = Data("{}".utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/health",
            response: .success(status: 200, body: body)
        )

        var ticks = [0.0, 0.42]
        let service = HealthCheckService(
            apiBaseURL: "https://api.example.com",
            supabaseURL: "https://sb.example.com",
            session: session,
            clock: { ticks.isEmpty ? 0.42 : ticks.removeFirst() }
        )

        let result = await service.check(.backend)

        XCTAssertEqual(result.latency ?? 0, 0.42, accuracy: 0.0001)
    }

    // MARK: - Supabase

    func testSupabaseReachableWhenAuthHealthReturns200() async {
        StubURLProtocol.register(
            host: "sb.example.com",
            path: "/auth/v1/health",
            response: .success(status: 200, body: Data())
        )

        let service = makeService()
        let result = await service.check(.supabaseAuth)

        XCTAssertTrue(result.reachable)
        XCTAssertEqual(result.statusCode, 200)
    }

    func testSupabaseUnreachableOn5xx() async {
        StubURLProtocol.register(
            host: "sb.example.com",
            path: "/auth/v1/health",
            response: .success(status: 502, body: Data())
        )

        let service = makeService()
        let result = await service.check(.supabaseAuth)

        XCTAssertFalse(result.reachable)
        XCTAssertEqual(result.statusCode, 502)
        XCTAssertEqual(result.error, "HTTP 502")
    }

    func testSupabaseEmptyURLSurfacesConfigError() async {
        let service = HealthCheckService(
            apiBaseURL: "https://api.example.com",
            supabaseURL: "",
            session: session,
            clock: { 0 }
        )

        let result = await service.check(.supabaseAuth)

        XCTAssertFalse(result.reachable)
        XCTAssertEqual(result.error, "Supabase URL is not configured")
    }

    // MARK: - Aggregate

    func testCheckAllReturnsOneResultPerComponent() async {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/health",
            response: .success(status: 200, body: Data("{}".utf8))
        )
        StubURLProtocol.register(
            host: "sb.example.com",
            path: "/auth/v1/health",
            response: .success(status: 200, body: Data())
        )

        let service = makeService()
        let report = await service.checkAll()

        XCTAssertEqual(report.results.count, HealthCheckResult.Component.allCases.count)
        XCTAssertTrue(report.allHealthy)
        XCTAssertNotNil(report.result(for: .backend))
        XCTAssertNotNil(report.result(for: .supabaseAuth))
    }

    func testCheckAllReportsPartialFailure() async {
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/health",
            response: .success(status: 200, body: Data("{}".utf8))
        )
        StubURLProtocol.register(
            host: "sb.example.com",
            path: "/auth/v1/health",
            response: .failure(URLError(.timedOut))
        )

        let service = makeService()
        let report = await service.checkAll()

        XCTAssertFalse(report.allHealthy)
        XCTAssertEqual(report.result(for: .backend)?.reachable, true)
        XCTAssertEqual(report.result(for: .supabaseAuth)?.reachable, false)
    }

    // MARK: - Helpers

    private func makeService() -> HealthCheckService {
        HealthCheckService(
            apiBaseURL: "https://api.example.com",
            supabaseURL: "https://sb.example.com",
            session: session,
            clock: { 0 }
        )
    }
}
