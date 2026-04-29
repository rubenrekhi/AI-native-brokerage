import Foundation
@testable import Sevino

final class MockTradingService: TradingServiceProtocol, @unchecked Sendable {

    // Stubs
    var listOrdersResult: Result<[OrderResponse], Error> = .success([])
    var listPositionsResult: Result<[PositionResponse], Error> = .success([])
    var placeOrderResult: Result<PlaceOrderResponse, Error> = .failure(NotStubbedError())
    var cancelOrderResult: Result<OrderDetailResponse, Error> = .failure(NotStubbedError())
    var getOrderResult: Result<OrderDetailResponse, Error> = .failure(NotStubbedError())

    // Call tracking
    private(set) var listOrdersCalls: [ListOrdersCall] = []
    private(set) var listPositionsCalls = 0
    private(set) var placeOrderCalls: [PlaceOrderRequest] = []
    private(set) var cancelOrderCalls: [String] = []
    private(set) var getOrderCalls: [String] = []

    struct NotStubbedError: Error {}

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

    func placeOrder(_ request: PlaceOrderRequest) async throws -> PlaceOrderResponse {
        placeOrderCalls.append(request)
        return try placeOrderResult.get()
    }

    func cancelOrder(id: String) async throws -> OrderDetailResponse {
        cancelOrderCalls.append(id)
        return try cancelOrderResult.get()
    }

    func getOrder(id: String) async throws -> OrderDetailResponse {
        getOrderCalls.append(id)
        return try getOrderResult.get()
    }
}
