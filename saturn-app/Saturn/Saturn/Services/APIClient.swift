import Auth
import Foundation
import Supabase

final class APIClient {
    static let shared = APIClient()

    private let baseURL: String
    private let session: URLSession

    private init() {
        self.baseURL = AppConfig.apiBaseURL
        self.session = URLSession.shared
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

        // Attach JWT from Supabase auth session
        if let session = try? await supabase.auth.session {
            urlRequest.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")
        }

        // Encode request body
        if let body {
            urlRequest.httpBody = try JSONEncoder().encode(body)
        }

        let (data, response) = try await session.data(for: urlRequest)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.unknown
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            if let apiError = try? JSONDecoder().decode(APIError.self, from: data) {
                throw apiError
            }
            throw APIError.unknown
        }

        return try JSONDecoder().decode(T.self, from: data)
    }
}

// Used as the default type for the optional body parameter
private struct Empty: Encodable {}
