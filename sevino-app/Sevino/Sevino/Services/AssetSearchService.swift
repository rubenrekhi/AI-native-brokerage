import Foundation

/// Protocol for searching the tradeable asset universe — enables mocking in previews and tests.
protocol AssetSearchServiceProtocol: Sendable {
    func search(query: String, limit: Int) async throws -> [AssetSearchResult]
}

extension AssetSearchServiceProtocol {
    func search(query: String) async throws -> [AssetSearchResult] {
        try await search(query: query, limit: 10)
    }
}

/// Calls `GET /v1/assets/search` against the Sevino API.
final class AssetSearchService: AssetSearchServiceProtocol {
    static let shared = AssetSearchService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func search(query: String, limit: Int = 10) async throws -> [AssetSearchResult] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }

        var components = URLComponents()
        components.path = "/v1/assets/search"
        components.queryItems = [
            URLQueryItem(name: "q", value: trimmed),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        // `URLComponents` percent-encodes the query items; `string` also includes the path.
        guard let path = components.string else {
            throw URLError(.badURL)
        }
        return try await api.get(path)
    }
}
