import Foundation

protocol APIClientProtocol: Sendable {
    func get<T: Decodable>(_ path: String) async throws -> T
    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func delete<T: Decodable>(_ path: String) async throws -> T
}

final class APIClient: APIClientProtocol {
    static let shared = APIClient()

    private let baseURL: String
    private let session: URLSession
    private let tokenProvider: @Sendable () async -> String?

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .iso8601
        return d
    }()

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

    func get<T: Decodable>(_ path: String) async throws -> T {
        try await request(path, method: "GET")
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
        body: (some Encodable)? = nil as Empty?
    ) async throws -> T {
        guard let url = URL(string: baseURL + path) else {
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
