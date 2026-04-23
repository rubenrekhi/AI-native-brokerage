import Foundation
@testable import Sevino

final class MockAssetSearchService: AssetSearchServiceProtocol, @unchecked Sendable {
    var resultsByQuery: [String: [AssetSearchResult]] = [:]
    var defaultResults: [AssetSearchResult] = []
    var errorToThrow: Error?

    private(set) var searchCallCount = 0
    private(set) var receivedQueries: [String] = []

    func search(query: String, limit: Int) async throws -> [AssetSearchResult] {
        searchCallCount += 1
        receivedQueries.append(query)
        if let error = errorToThrow { throw error }
        return resultsByQuery[query] ?? defaultResults
    }
}
