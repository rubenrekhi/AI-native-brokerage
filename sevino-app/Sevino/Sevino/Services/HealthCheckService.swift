import Foundation

/**
 Snapshot of a single component's health.

 `reachable` means the probe got a 2xx response within the timeout.
 `latency` is set when the probe succeeded, `error` when it failed.
 `details` carries any body payload that can be surfaced (e.g. the
 backend `/health` response reports db + redis sub-statuses).
 */
struct HealthCheckResult: Equatable, Sendable {
    let component: Component
    let reachable: Bool
    let latency: TimeInterval?
    let statusCode: Int?
    let error: String?
    let details: [String: String]

    enum Component: String, CaseIterable, Sendable {
        case backend
        case supabaseAuth
    }

    init(
        component: Component,
        reachable: Bool,
        latency: TimeInterval? = nil,
        statusCode: Int? = nil,
        error: String? = nil,
        details: [String: String] = [:]
    ) {
        self.component = component
        self.reachable = reachable
        self.latency = latency
        self.statusCode = statusCode
        self.error = error
        self.details = details
    }
}

/// Aggregate result of probing every component.
struct HealthReport: Equatable, Sendable {
    let results: [HealthCheckResult]

    var allHealthy: Bool { results.allSatisfy(\.reachable) }

    func result(for component: HealthCheckResult.Component) -> HealthCheckResult? {
        results.first { $0.component == component }
    }
}

protocol HealthCheckServiceProtocol: Sendable {
    func check(_ component: HealthCheckResult.Component) async -> HealthCheckResult
    func checkAll() async -> HealthReport
}

/**
 Probes the backend `/health` and Supabase `/auth/v1/health` endpoints.

 Uses a dedicated URLSession with short timeouts so a dead host fails
 fast instead of hanging the caller. The service never throws — every
 failure is represented in `HealthCheckResult` so UI layers can render
 a per-component status without try/catch plumbing.
 */
final class HealthCheckService: HealthCheckServiceProtocol {
    static let shared = HealthCheckService()

    private let apiBaseURL: String
    private let supabaseURL: String
    private let session: URLSession
    private let clock: @Sendable () -> TimeInterval

    init(
        apiBaseURL: String = AppConfig.apiBaseURL,
        supabaseURL: String = AppConfig.supabaseURL,
        session: URLSession = HealthCheckService.defaultSession(),
        clock: @escaping @Sendable () -> TimeInterval = {
            Date.now.timeIntervalSinceReferenceDate
        }
    ) {
        self.apiBaseURL = apiBaseURL
        self.supabaseURL = supabaseURL
        self.session = session
        self.clock = clock
    }

    static func defaultSession(timeout: TimeInterval = 3.0) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        return URLSession(configuration: config)
    }

    func check(_ component: HealthCheckResult.Component) async -> HealthCheckResult {
        switch component {
        case .backend:
            return await probeBackend()
        case .supabaseAuth:
            return await probeSupabaseAuth()
        }
    }

    func checkAll() async -> HealthReport {
        // Run probes in parallel — each is network-bound, no ordering needed.
        async let backend = probeBackend()
        async let supabase = probeSupabaseAuth()
        return HealthReport(results: [await backend, await supabase])
    }

    private func probeBackend() async -> HealthCheckResult {
        guard !apiBaseURL.isEmpty, let url = URL(string: apiBaseURL + "/health") else {
            return HealthCheckResult(
                component: .backend,
                reachable: false,
                error: "API base URL is not configured"
            )
        }
        return await probe(component: .backend, url: url) { data in
            // Backend returns {"status": "ok", "db": "ok", "redis": "ok"}
            // (or "degraded" with 503 — which the caller treats as unreachable).
            guard
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return [:] }
            return json.compactMapValues { $0 as? String }
        }
    }

    private func probeSupabaseAuth() async -> HealthCheckResult {
        guard
            !supabaseURL.isEmpty,
            let url = URL(string: supabaseURL)?.appendingPathComponent("auth/v1/health")
        else {
            return HealthCheckResult(
                component: .supabaseAuth,
                reachable: false,
                error: "Supabase URL is not configured"
            )
        }
        return await probe(component: .supabaseAuth, url: url) { _ in [:] }
    }

    private func probe(
        component: HealthCheckResult.Component,
        url: URL,
        parseDetails: (Data) -> [String: String]
    ) async -> HealthCheckResult {
        let start = clock()
        do {
            var request = URLRequest(url: url)
            request.httpMethod = "GET"
            let (data, response) = try await session.data(for: request)
            let latency = clock() - start
            guard let http = response as? HTTPURLResponse else {
                return HealthCheckResult(
                    component: component,
                    reachable: false,
                    latency: latency,
                    error: "Non-HTTP response"
                )
            }
            let ok = (200..<300).contains(http.statusCode)
            return HealthCheckResult(
                component: component,
                reachable: ok,
                latency: latency,
                statusCode: http.statusCode,
                error: ok ? nil : "HTTP \(http.statusCode)",
                details: parseDetails(data)
            )
        } catch {
            return HealthCheckResult(
                component: component,
                reachable: false,
                latency: clock() - start,
                error: error.localizedDescription
            )
        }
    }
}
