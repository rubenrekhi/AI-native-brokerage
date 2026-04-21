import Foundation
@testable import Sevino

final class MockRadarService: RadarServiceProtocol {
    var fetchRadarError: Error?
    var radarItems: [RadarItem] = []

    private(set) var fetchRadarCallCount = 0

    func fetchRadar() async throws -> [RadarItem] {
        fetchRadarCallCount += 1
        if let error = fetchRadarError { throw error }
        return radarItems
    }
}
