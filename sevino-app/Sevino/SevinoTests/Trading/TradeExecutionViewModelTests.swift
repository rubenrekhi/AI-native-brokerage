#if DEBUG
import XCTest
@testable import Sevino

@MainActor
final class TradeExecutionViewModelTests: XCTestCase {

    private func makeSUT(
        mock: MockTradingService = MockTradingService()
    ) -> (TradeExecutionViewModel, MockTradingService) {
        (TradeExecutionViewModel(tradingService: mock), mock)
    }

    private func makePlaceResponse(
        id: String = "ord_1",
        status: String = "accepted"
    ) -> PlaceOrderResponse {
        PlaceOrderResponse(
            id: id,
            alpacaOrderId: "alp_\(id)",
            symbol: "AAPL",
            side: "buy",
            type: "market",
            timeInForce: "day",
            qty: nil,
            notional: "100.00",
            limitPrice: nil,
            status: status,
            submittedAt: nil,
            createdAt: "2026-04-28T10:00:00Z"
        )
    }

    private func makeDetailResponse(
        id: String = "ord_1",
        status: String = "canceled"
    ) -> OrderDetailResponse {
        OrderDetailResponse(
            id: id,
            alpacaOrderId: "alp_\(id)",
            symbol: "AAPL",
            side: "buy",
            type: "market",
            timeInForce: "day",
            qty: nil,
            notional: "100.00",
            limitPrice: nil,
            status: status,
            submittedAt: nil,
            createdAt: "2026-04-28T10:00:00Z",
            filledQty: nil,
            filledAvgPrice: nil,
            filledAt: nil,
            conversationId: nil
        )
    }

    // MARK: - prepareTrade

    func test_prepareTrade_buildsCardDataFromInputs() {
        let (sut, _) = makeSUT()
        sut.symbol = "tsla"
        sut.side = .sell
        sut.orderType = .market
        sut.amount = "250.00"
        sut.amountType = .notional

        sut.prepareTrade()

        let card = try? XCTUnwrap(sut.cardData)
        XCTAssertEqual(card?.ticker, "TSLA")
        XCTAssertEqual(card?.side, .sell)
        XCTAssertEqual(card?.orderType, "Market Order")
        XCTAssertEqual(card?.amount, "$250.00")
        XCTAssertEqual(card?.estimatedTotal, "$250.00")
        XCTAssertEqual(sut.tradeState, .pending)
    }

    func test_prepareTrade_limitOrderIncludesLimitPriceInOrderType() {
        let (sut, _) = makeSUT()
        sut.symbol = "AMD"
        sut.orderType = .limit
        sut.limitPrice = "150.50"

        sut.prepareTrade()

        XCTAssertEqual(sut.cardData?.orderType, "Limit Order @ $150.50")
    }

    func test_prepareTrade_resetsPriorOutcome() {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse())
        sut.prepareTrade()

        let exp = expectation(description: "submitted")
        Task {
            await sut.confirmTrade()
            exp.fulfill()
        }
        wait(for: [exp], timeout: 1.0)
        XCTAssertEqual(sut.tradeState, .success)
        XCTAssertNotNil(sut.lastOrderId)

        sut.prepareTrade()

        XCTAssertEqual(sut.tradeState, .pending)
        XCTAssertNil(sut.lastOrderId)
        XCTAssertNil(sut.lastOrderStatus)
    }

    // MARK: - confirmTrade

    func test_confirmTrade_success_setsLastOrderIdAndState() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse(id: "ord_42", status: "accepted"))
        sut.prepareTrade()

        await sut.confirmTrade()

        XCTAssertEqual(sut.tradeState, .success)
        XCTAssertEqual(sut.lastOrderId, "ord_42")
        XCTAssertEqual(sut.lastOrderStatus, "accepted")
        XCTAssertEqual(mock.placeOrderCalls.count, 1)
    }

    func test_confirmTrade_sendsRequestBuiltFromInputs() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse())
        sut.symbol = "msft"
        sut.side = .buy
        sut.orderType = .limit
        sut.limitPrice = "300.00"
        sut.amountType = .qty
        sut.amount = "5"

        await sut.confirmTrade()

        let request = try? XCTUnwrap(mock.placeOrderCalls.first)
        XCTAssertEqual(request?.symbol, "MSFT")
        XCTAssertEqual(request?.side, "buy")
        XCTAssertEqual(request?.type, "limit")
        XCTAssertEqual(request?.qty, "5")
        XCTAssertNil(request?.notional)
        XCTAssertEqual(request?.limitPrice, "300.00")
    }

    func test_confirmTrade_apiError_surfacesBackendMessage() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .failure(
            APIError(error: "Insufficient buying power", code: APIError.Code.validationError)
        )
        sut.prepareTrade()

        await sut.confirmTrade()

        XCTAssertEqual(sut.tradeState, .error("Insufficient buying power"))
        XCTAssertNil(sut.lastOrderId)
    }

    func test_confirmTrade_genericError_fallsBackToLocalizedDescription() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .failure(TestError.boom)
        sut.prepareTrade()

        await sut.confirmTrade()

        if case .error(let message) = sut.tradeState {
            XCTAssertEqual(message, TestError.boom.localizedDescription)
        } else {
            XCTFail("Expected error state, got \(sut.tradeState)")
        }
    }

    // MARK: - cancelTrade

    func test_cancelTrade_success_updatesStatus() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse(id: "ord_7"))
        mock.cancelOrderResult = .success(makeDetailResponse(id: "ord_7", status: "canceled"))
        sut.prepareTrade()
        await sut.confirmTrade()

        await sut.cancelTrade()

        XCTAssertEqual(mock.cancelOrderCalls, ["ord_7"])
        XCTAssertEqual(sut.lastOrderStatus, "canceled")
        XCTAssertEqual(sut.tradeState, .success)
    }

    func test_cancelTrade_withoutPriorOrder_isNoOp() async {
        let (sut, mock) = makeSUT()

        await sut.cancelTrade()

        XCTAssertTrue(mock.cancelOrderCalls.isEmpty)
    }

    func test_cancelTrade_terminalOrderError_surfacesMessageOnActionError() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse(id: "ord_9"))
        mock.cancelOrderResult = .failure(
            APIError(error: "Order is no longer cancellable", code: APIError.Code.conflict)
        )
        sut.prepareTrade()
        await sut.confirmTrade()

        await sut.cancelTrade()

        XCTAssertEqual(sut.actionError, "Order is no longer cancellable")
        XCTAssertEqual(sut.tradeState, .success)
    }

    // MARK: - pollStatus

    func test_pollStatus_updatesStatusFromBackend() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse(id: "ord_3", status: "accepted"))
        mock.getOrderResult = .success(makeDetailResponse(id: "ord_3", status: "filled"))
        sut.prepareTrade()
        await sut.confirmTrade()

        await sut.pollStatus()

        XCTAssertEqual(mock.getOrderCalls, ["ord_3"])
        XCTAssertEqual(sut.lastOrderStatus, "filled")
    }

    func test_pollStatus_withoutPriorOrder_isNoOp() async {
        let (sut, mock) = makeSUT()

        await sut.pollStatus()

        XCTAssertTrue(mock.getOrderCalls.isEmpty)
    }

    func test_pollStatus_apiError_surfacesActionErrorWithoutDowngradingTradeState() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse(id: "ord_4"))
        mock.getOrderResult = .failure(
            APIError(error: "Service unavailable", code: APIError.Code.unknown)
        )
        sut.prepareTrade()
        await sut.confirmTrade()

        await sut.pollStatus()

        XCTAssertEqual(sut.actionError, "Service unavailable")
        XCTAssertEqual(sut.tradeState, .success)
    }

    // MARK: - Confirm/cancel/poll concurrency guards

    func test_confirmTrade_notional_setsNotionalAndOmitsQty() async {
        let (sut, mock) = makeSUT()
        mock.placeOrderResult = .success(makePlaceResponse())
        sut.symbol = "googl"
        sut.amountType = .notional
        sut.amount = "500.00"
        sut.orderType = .market

        await sut.confirmTrade()

        let request = try? XCTUnwrap(mock.placeOrderCalls.first)
        XCTAssertEqual(request?.notional, "500.00")
        XCTAssertNil(request?.qty)
        XCTAssertNil(request?.limitPrice)
    }

    func test_confirmTrade_whileSubmitting_isNoOp() async {
        let mock = SuspendingTradingService(response: makePlaceResponse())
        let sut = TradeExecutionViewModel(tradingService: mock)
        sut.prepareTrade()

        let inFlight = Task { await sut.confirmTrade() }
        await mock.waitUntilEntered()
        XCTAssertTrue(sut.isSubmitting)

        await sut.confirmTrade()

        mock.resume()
        await inFlight.value

        XCTAssertEqual(mock.callCount, 1)
    }

    private enum TestError: LocalizedError {
        case boom
        var errorDescription: String? { "boom" }
    }
}

/// Lets the test observe that `placeOrder` has been entered, holds the
/// network call open until `resume()` is called, then returns the stub
/// response. Used to exercise reentrancy guards.
private final class SuspendingTradingService: TradingServiceProtocol, @unchecked Sendable {
    private let response: PlaceOrderResponse
    private let entered = AsyncSemaphore()
    private let gate = AsyncSemaphore()
    private(set) var callCount: Int = 0

    init(response: PlaceOrderResponse) {
        self.response = response
    }

    func waitUntilEntered() async { await entered.wait() }
    func resume() { gate.signal() }

    func placeOrder(_ request: PlaceOrderRequest) async throws -> PlaceOrderResponse {
        callCount += 1
        entered.signal()
        await gate.wait()
        return response
    }

    func listOrders(status: String?, side: String?, symbols: String?, after: Date?, until: Date?, limit: Int) async throws -> [OrderResponse] { [] }
    func listPositions() async throws -> [PositionResponse] { [] }
    func cancelOrder(id: String) async throws -> OrderDetailResponse { fatalError() }
    func getOrder(id: String) async throws -> OrderDetailResponse { fatalError() }
}

private final class AsyncSemaphore: @unchecked Sendable {
    private var continuations: [CheckedContinuation<Void, Never>] = []
    private var pendingSignals: Int = 0
    private let lock = NSLock()

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if pendingSignals > 0 {
                pendingSignals -= 1
                lock.unlock()
                continuation.resume()
            } else {
                continuations.append(continuation)
                lock.unlock()
            }
        }
    }

    func signal() {
        lock.lock()
        if continuations.isEmpty {
            pendingSignals += 1
            lock.unlock()
        } else {
            let continuation = continuations.removeFirst()
            lock.unlock()
            continuation.resume()
        }
    }
}
#endif
