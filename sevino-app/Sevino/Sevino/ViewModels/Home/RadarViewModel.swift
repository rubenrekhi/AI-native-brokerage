import Foundation

@Observable
final class RadarViewModel {
    private let client: any RadarAPIClientProtocol

    private(set) var radarItems: [RadarItem] = []
    private(set) var nextRefreshAt: Date?
    private(set) var isLoading = false
    private(set) var error: String?

    init(client: any RadarAPIClientProtocol = RadarAPIClient()) {
        self.client = client
    }

    func loadRadar() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await client.fetchRadar()
            radarItems = response.items
            nextRefreshAt = response.nextRefreshAt
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func toggleStar(itemId: UUID) async {
        guard let item = radarItems.first(where: { $0.id == itemId }) else { return }
        let desired = !item.isStarred
        do {
            let updated = try await client.toggleFavorite(itemId: itemId, isFavorited: desired)
            guard updated != nil else {
                // Server deletes a user_added row when it's unfavorited (responds 204).
                radarItems.removeAll { $0.id == itemId }
                return
            }
            // PATCH response omits the GET-only price/change overlay, so flip the flag
            // in place rather than replacing the row and dropping its display fields.
            if let idx = radarItems.firstIndex(where: { $0.id == itemId }) {
                radarItems[idx].isStarred = desired
            }
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }
}
