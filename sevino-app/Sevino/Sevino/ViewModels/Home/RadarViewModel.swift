import Foundation

@Observable
final class RadarViewModel {
    private let client: any RadarAPIClientProtocol

    private(set) var radarItems: [RadarItem] = []
    private(set) var nextRefreshAt: Date?
    private(set) var isLoading = false
    private(set) var error: String?

    var activeTab: RadarTab = .new

    /// True once the first successful fetch has applied the default tab.
    /// Subsequent reloads (manual retry, app foreground refresh) leave
    /// `activeTab` alone so we don't yank the user back to New after
    /// they've intentionally switched to Starred.
    private var hasAppliedDefaultTab = false

    /// This week's unstarred AI picks, best match first.
    private(set) var newItems: [RadarItem] = []

    /// The persistent watchlist (any source), most recently added first.
    private(set) var starredItems: [RadarItem] = []

    /// Localized weekday of the next batch, or nil when there is no future
    /// anchor (first batch still generating). Drives the New-tab empty copy.
    var nextRefreshWeekday: String? {
        guard let nextRefreshAt, nextRefreshAt > .now else { return nil }
        return nextRefreshAt.formatted(.dateTime.weekday(.wide))
    }

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
            recomputeTabs()
            if !hasAppliedDefaultTab {
                activeTab = newItems.isEmpty ? .starred : .new
                hasAppliedDefaultTab = true
            }
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
                recomputeTabs()
                return
            }
            // PATCH response omits the GET-only price/change overlay, so flip the flag
            // in place rather than replacing the row and dropping its display fields.
            if let idx = radarItems.firstIndex(where: { $0.id == itemId }) {
                radarItems[idx].isStarred = desired
            }
            recomputeTabs()
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }

    private func recomputeTabs() {
        newItems = radarItems
            .filter { !$0.isStarred && $0.source == .aiGenerated }
            .sorted { ($0.relevanceScore ?? 0) > ($1.relevanceScore ?? 0) }
        starredItems = radarItems
            .filter(\.isStarred)
            .sorted { $0.createdAt > $1.createdAt }
    }
}
