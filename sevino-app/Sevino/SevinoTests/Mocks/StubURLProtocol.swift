import Foundation

/**
 Intercepts URL loading so tests can stub HTTP responses without hitting the network.

 Register a response for a host + path before making the request. Unmatched
 requests produce a clear assertion-style error so mistakes fail loudly
 instead of silently hitting the real network.
 */
final class StubURLProtocol: URLProtocol {

    enum StubResponse {
        case success(status: Int, body: Data, headers: [String: String] = [:])
        case failure(Error)
    }

    private struct Key: Hashable {
        let host: String
        let path: String
    }

    // URLProtocol needs global state — URLSession instantiates one protocol per
    // request, so there's no per-session handle for tests to thread in.
    nonisolated(unsafe) private static var stubs: [Key: StubResponse] = [:]
    nonisolated(unsafe) private(set) static var recordedRequests: [URLRequest] = []
    private static let lock = NSLock()

    static func register(host: String, path: String, response: StubResponse) {
        lock.lock()
        defer { lock.unlock() }
        stubs[Key(host: host, path: path)] = response
    }

    static func reset() {
        lock.lock()
        defer { lock.unlock() }
        stubs.removeAll()
        recordedRequests.removeAll()
    }

    static func lastRequest() -> URLRequest? {
        lock.lock()
        defer { lock.unlock() }
        return recordedRequests.last
    }

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        Self.recordedRequests.append(request)
        let stub = request.url.flatMap { url -> StubResponse? in
            guard let host = url.host else { return nil }
            return Self.stubs[Key(host: host, path: url.path)]
        }
        Self.lock.unlock()

        guard let stub else {
            client?.urlProtocol(
                self,
                didFailWithError: URLError(
                    .resourceUnavailable,
                    userInfo: [NSLocalizedDescriptionKey: "No stub registered for \(request.url?.absoluteString ?? "nil")"]
                )
            )
            return
        }

        switch stub {
        case .success(let status, let body, let headers):
            guard let url = request.url else { return }
            guard let response = HTTPURLResponse(
                url: url,
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: headers
            ) else {
                client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
                return
            }
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: body)
            client?.urlProtocolDidFinishLoading(self)
        case .failure(let error):
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

extension StubURLProtocol {
    /// Returns a fresh ephemeral URLSession routed through this stub protocol,
    /// and clears any previously-registered stubs/recordings.
    static func makeSession() -> URLSession {
        reset()
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: config)
    }
}
