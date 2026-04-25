import Foundation
@testable import Sevino

final class MockTradingService: TradingServiceProtocol, @unchecked Sendable {

    // Stubs
    var listOrdersResult: Result<[OrderResponse], Error> = .success([])
    var listPositionsResult: Result<[PositionResponse], Error> = .success([])

    // Call tracking
    private(set) var listOrdersCalls: [ListOrdersCall] = []
    private(set) var listPositionsCalls = 0

    struct ListOrdersCall: Equatable {
        let status: String?
        let side: String?
        let symbols: String?
        let after: Date?
        let until: Date?
        let limit: Int
    }

    func listOrders(
        status: String?,
        side: String?,
        symbols: String?,
        after: Date?,
        until: Date?,
        limit: Int
    ) async throws -> [OrderResponse] {
        listOrdersCalls.append(
            ListOrdersCall(
                status: status,
                side: side,
                symbols: symbols,
                after: after,
                until: until,
                limit: limit
            )
        )
        return try listOrdersResult.get()
    }

    func listPositions() async throws -> [PositionResponse] {
        listPositionsCalls += 1
        return try listPositionsResult.get()
    }
}
