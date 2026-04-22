import XCTest
@testable import Sevino

/**
 Integration tests that hit a real local Sevino API (`make server` in sevino-api/).
 Skipped unless `INTEGRATION_TESTS=1` and `SEVINO_API_TEST_URL` / `SUPABASE_TEST_URL`
 are set and the endpoints are reachable — same gating as AuthServiceIntegrationTests.
 */
@MainActor
final class HealthCheckIntegrationTests: XCTestCase {

    private var apiBaseURL: String!
    private var supabaseURL: String!

    override func setUp() async throws {
        let env = ProcessInfo.processInfo.environment

        try XCTSkipUnless(
            env["INTEGRATION_TESTS"] == "1",
            "Set INTEGRATION_TESTS=1 to run"
        )

        let apiURL = env["SEVINO_API_TEST_URL"] ?? "http://127.0.0.1:8000"
        let sbURL = env["SUPABASE_TEST_URL"]

        try XCTSkipUnless(sbURL != nil, "SUPABASE_TEST_URL must be set")

        guard let apiBase = URL(string: apiURL) else {
            throw XCTSkip("SEVINO_API_TEST_URL is not a valid URL: \(apiURL)")
        }

        if let reason = await Self.unreachableReason(for: apiBase.appendingPathComponent("health")) {
            throw XCTSkip("Sevino API not reachable at \(apiURL): \(reason). Run `make server` in sevino-api/.")
        }

        self.apiBaseURL = apiURL
        self.supabaseURL = sbURL
    }

    func testBackendHealthIsReachable() async throws {
        let service = HealthCheckService(
            apiBaseURL: apiBaseURL,
            supabaseURL: supabaseURL
        )

        let result = await service.check(.backend)

        XCTAssertTrue(result.reachable, "expected /health to return 2xx, got \(String(describing: result.error))")
        XCTAssertEqual(result.statusCode, 200)
        XCTAssertEqual(result.details["status"], "ok")
    }

    func testSupabaseAuthHealthIsReachable() async throws {
        let service = HealthCheckService(
            apiBaseURL: apiBaseURL,
            supabaseURL: supabaseURL
        )

        let result = await service.check(.supabaseAuth)

        XCTAssertTrue(result.reachable, "expected Supabase auth /health to return 2xx, got \(String(describing: result.error))")
    }

    func testCheckAllReportsHealthyLocalStack() async throws {
        let service = HealthCheckService(
            apiBaseURL: apiBaseURL,
            supabaseURL: supabaseURL
        )

        let report = await service.checkAll()

        XCTAssertTrue(
            report.allHealthy,
            "one or more components unhealthy: \(report.results.map { "\($0.component.rawValue)=\($0.error ?? "ok")" })"
        )
    }

    private static func unreachableReason(for url: URL) async -> String? {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2.0
        config.timeoutIntervalForResource = 2.0
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }

        do {
            let (_, response) = try await session.data(from: url)
            guard let http = response as? HTTPURLResponse else { return "non-HTTP response" }
            guard (200..<300).contains(http.statusCode) else { return "HTTP \(http.statusCode)" }
            return nil
        } catch {
            return error.localizedDescription
        }
    }
}
