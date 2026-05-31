import Foundation
@testable import Sevino

final class MockRadarAPIClient: RadarAPIClientProtocol, @unchecked Sendable {
    var fetchResponse = RadarListResponse(items: [], nextRefreshAt: nil)
    var fetchError: Error?

    /// Result returned by `toggleFavorite`. `.some(nil)` models a 204 (the
    /// server deleted the row); `.some(item)` models a 200.
    var toggleResult: RadarItem??
    var toggleError: Error?

    var addResult: RadarItem?
    var addError: Error?
    var deleteError: Error?

    private(set) var fetchCallCount = 0
    private(set) var toggleCalls: [(itemId: UUID, isFavorited: Bool)] = []
    private(set) var deletedItemIds: [UUID] = []
    private(set) var addedSymbols: [String] = []

    func fetchRadar() async throws -> RadarListResponse {
        fetchCallCount += 1
        if let fetchError { throw fetchError }
        return fetchResponse
    }

    func toggleFavorite(itemId: UUID, isFavorited: Bool) async throws -> RadarItem? {
        toggleCalls.append((itemId, isFavorited))
        if let toggleError { throw toggleError }
        if case let .some(item) = toggleResult { return item }
        return nil
    }

    func deleteRadarItem(itemId: UUID) async throws {
        deletedItemIds.append(itemId)
        if let deleteError { throw deleteError }
    }

    func addRadarItem(symbol: String) async throws -> RadarItem {
        addedSymbols.append(symbol)
        if let addError { throw addError }
        guard let addResult else { throw URLError(.badServerResponse) }
        return addResult
    }
}
