import Foundation

protocol ShortcutsAPIClientProtocol: Sendable {
    func fetchShortcuts() async throws -> [Shortcut]
}

/// Calls `GET /v1/shortcuts` and unwraps the `{ "items": [...] }` envelope.
final class ShortcutsAPIClient: ShortcutsAPIClientProtocol {
    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func fetchShortcuts() async throws -> [Shortcut] {
        let response: ShortcutsResponse = try await api.get("/v1/shortcuts")
        return response.items
    }
}

private struct ShortcutsResponse: Decodable, Sendable {
    let items: [Shortcut]
}
