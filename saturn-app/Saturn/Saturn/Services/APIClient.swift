import Auth
import Foundation
import Supabase

enum APIError: Error {
    case unauthorized
    case notFound
    case serverError(statusCode: Int)
    case networkError(Error)
    case decodingError(Error)
    case invalidURL
}

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

    private func request<T: Decodable>(
        _ path: String,
        method: String,
        body: (some Encodable)? = nil as Empty?
    ) async throws -> T {
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL
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

        // Send request
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest)
        } catch {
            throw APIError.networkError(error)
        }

        // Check status code
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.serverError(statusCode: 0)
        }

        switch httpResponse.statusCode {
        case 200..<300:
            break
        case 401:
            throw APIError.unauthorized
        case 404:
            throw APIError.notFound
        default:
            throw APIError.serverError(statusCode: httpResponse.statusCode)
        }

        // Decode response
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decodingError(error)
        }
    }
}

// Used as the default type for the optional body parameter
private struct Empty: Encodable {}
