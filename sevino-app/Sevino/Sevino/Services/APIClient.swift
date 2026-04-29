import Foundation

protocol APIClientProtocol: Sendable {
    func get<T: Decodable>(_ path: String, query: [String: String]) async throws -> T
    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func delete<T: Decodable>(_ path: String) async throws -> T
}

extension APIClientProtocol {
    func get<T: Decodable>(_ path: String) async throws -> T {
        try await get(path, query: [:])
    }
}

final class APIClient: APIClientProtocol {
    static let shared = APIClient()

    static func makeEncoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }

    /// Mirrors what the live client uses on the wire — tests should call this
    /// instead of building their own `JSONDecoder` so backend-decoder drift
    /// (e.g. snake-case keys, fractional-second timestamps) is caught here too.
    static func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let raw = try container.decode(String.self)
            if let date = _isoFractional.date(from: raw) { return date }
            if let date = _isoPlain.date(from: raw) { return date }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO-8601 date: \(raw)"
            )
        }
        return d
    }

    private let baseURL: String
    private let session: URLSession
    private let tokenProvider: @Sendable () async -> String?

    private let encoder: JSONEncoder = APIClient.makeEncoder()
    private let decoder: JSONDecoder = APIClient.makeDecoder()

    init(
        baseURL: String = AppConfig.apiBaseURL,
        session: URLSession = .shared,
        tokenProvider: @escaping @Sendable () async -> String? = {
            await (AuthService.shared as AuthServiceProtocol).accessToken
        }
    ) {
        self.baseURL = baseURL
        self.session = session
        self.tokenProvider = tokenProvider
    }

    func get<T: Decodable>(_ path: String, query: [String: String]) async throws -> T {
        try await request(path, method: "GET", query: query)
    }

    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        try await request(path, method: "POST", body: body)
    }

    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        try await request(path, method: "PUT", body: body)
    }

    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        try await request(path, method: "PATCH", body: body)
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        try await request(path, method: "DELETE")
    }

    /**
     Throws `APIError` on non-2xx, `URLError` on network failure,
     `DecodingError` if the success body can't be decoded into `T`.
     */
    private func request<T: Decodable>(
        _ path: String,
        method: String,
        query: [String: String] = [:],
        body: (some Encodable)? = nil as Empty?
    ) async throws -> T {
        guard var components = URLComponents(string: baseURL + path) else {
            throw URLError(.badURL)
        }
        if !query.isEmpty {
            components.queryItems = query
                .sorted(by: { $0.key < $1.key })
                .map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        guard let url = components.url else {
            throw URLError(.badURL)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = method
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")

        // Attach API key if configured
        let apiKey = AppConfig.apiKey
        if !apiKey.isEmpty {
            urlRequest.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        }

        if let token = await tokenProvider() {
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body {
            urlRequest.httpBody = try encoder.encode(body)
        }

        let (data, response) = try await session.data(for: urlRequest)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.unknown
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            if let apiError = try? decoder.decode(APIError.self, from: data) {
                throw apiError
            }
            throw APIError.unknown
        }

        return try decoder.decode(T.self, from: data)
    }
}

// Used as the default type for the optional body parameter
private struct Empty: Encodable {}

// Pydantic v2 emits ISO-8601 with fractional seconds by default
// (e.g. "2026-04-24T12:34:56.789012+00:00"); some serializers strip them.
// Try the fractional variant first, then fall back to plain.
private let _isoFractional: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()

private let _isoPlain: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f
}()
