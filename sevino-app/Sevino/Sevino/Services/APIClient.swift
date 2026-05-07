import Foundation

protocol APIClientProtocol: Sendable {
    func get<T: Decodable>(_ path: String) async throws -> T
    func post<T: Decodable>(_ path: String) async throws -> T
    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func post(_ path: String) async throws
    func post(_ path: String, body: some Encodable) async throws
    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T
    func delete<T: Decodable>(_ path: String) async throws -> T
    func delete(_ path: String) async throws
    func delete(_ path: String, body: some Encodable) async throws
    func downloadFile(_ path: String, suggestedExtension: String?) async throws -> URL
}

final class APIClient: APIClientProtocol {
    static let shared = APIClient()

    private let baseURL: String
    private let session: URLSession
    private let tokenProvider: @Sendable () async -> String?

    private let encoder = JSONEncoder.sevino()
    private let decoder = JSONDecoder.sevino()

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

    func post<T: Decodable>(_ path: String) async throws -> T {
        try await request(path, method: "POST")
    }

    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T {
        try await request(path, method: "POST", body: body)
    }

    /// POST variant for endpoints that return 204 No Content (or whose response
    /// body the caller doesn't care about).
    func post(_ path: String) async throws {
        try await requestVoid(path, method: "POST")
    }

    func post(_ path: String, body: some Encodable) async throws {
        try await requestVoid(path, method: "POST", body: body)
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

    /// DELETE variant for endpoints that return 204 No Content with an empty body.
    func delete(_ path: String) async throws {
        try await requestVoid(path, method: "DELETE")
    }

    /// DELETE with a request body — used when the endpoint requires a confirmation
    /// payload (e.g. `{"confirmation": "DELETE"}`) and returns 204 No Content.
    func delete(_ path: String, body: some Encodable) async throws {
        try await requestVoid(path, method: "DELETE", body: body)
    }

    /// Downloads the raw response body for `path` (after following redirects)
    /// and writes it to a temp file, returning the local file URL.
    /// Useful for binary payloads like PDF documents that can then be handed
    /// off to QuickLook or a share sheet.
    func downloadFile(_ path: String, suggestedExtension: String? = nil) async throws -> URL {
        guard let url = URL(string: baseURL + path) else {
            throw URLError(.badURL)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = "GET"

        let apiKey = AppConfig.apiKey
        if !apiKey.isEmpty {
            urlRequest.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        }

        if let token = await tokenProvider() {
            urlRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
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

        let filename = UUID().uuidString + (suggestedExtension.map { ".\($0)" } ?? "")
        let fileURL = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        try data.write(to: fileURL, options: .atomic)
        return fileURL
    }

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

    private func requestVoid(
        _ path: String,
        method: String,
        body: (some Encodable)? = nil as Empty?
    ) async throws {
        guard let url = URL(string: baseURL + path) else {
            throw URLError(.badURL)
        }

        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = method
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")

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
    }
}

// Concrete Encodable sentinel satisfying the generic default `nil as Empty?` —
// allows callers to omit `body` without specifying a type.
private struct Empty: Encodable {}
