import XCTest
@testable import Sevino

@MainActor
final class CancelOrderCardViewModelTests: XCTestCase {

    private func makeBlock(status: OrderCancellationStatus = .pending) -> CancelOrderBlock {
        CancelOrderBlock(
            blockId: "blk_1",
            orderId: "ord_1",
            symbol: "AAPL",
            companyName: "Apple Inc.",
            side: .buy,
            orderType: .market,
            qty: 10,
            notional: nil,
            limitPrice: nil,
            filledQty: 0,
            timeInForce: "day",
            submittedAt: Date(timeIntervalSince1970: 1_780_000_000),
            status: status
        )
    }

    func test_cancel_happyPath_setsCancelledAndPassesOrderId() async {
        let recorder = OrderIdRecorder()
        let sut = CancelOrderCardViewModel(block: makeBlock()) { orderId in
            recorder.value = orderId
        }

        await sut.cancel()

        XCTAssertEqual(sut.localStatus, .cancelled)
        XCTAssertNil(sut.error)
        XCTAssertFalse(sut.isCancelling)
        XCTAssertEqual(recorder.value, "ord_1")
    }

    func test_cancel_notCancellableError_setsFailedAndNotRetryable() async {
        let sut = CancelOrderCardViewModel(block: makeBlock()) { _ in
            throw OrderNotCancellableError(message: "Order already filled")
        }

        await sut.cancel()

        XCTAssertEqual(sut.localStatus, .failed)
        XCTAssertEqual(sut.error, "Order already filled")
        XCTAssertFalse(sut.isRetryable)
    }

    func test_cancel_conflictAPIError_setsFailedAndNotRetryable() async {
        let sut = CancelOrderCardViewModel(block: makeBlock()) { _ in
            throw APIError(error: "Order is no longer cancellable", code: APIError.Code.conflict)
        }

        await sut.cancel()

        XCTAssertEqual(sut.localStatus, .failed)
        XCTAssertEqual(sut.error, "Order is no longer cancellable")
        XCTAssertFalse(sut.isRetryable)
    }

    func test_cancel_afterTerminalFailure_blocksFurtherAttempts() async {
        let attempts = AttemptCounter()
        let sut = CancelOrderCardViewModel(block: makeBlock()) { _ in
            attempts.count += 1
            throw OrderNotCancellableError(message: "Order already filled")
        }

        await sut.cancel()
        XCTAssertFalse(sut.isRetryable)

        await sut.cancel()
        XCTAssertEqual(attempts.count, 1)
    }

    func test_cancel_transientError_setsFailedRetryableAndRetrySucceeds() async {
        let attempts = AttemptCounter()
        let sut = CancelOrderCardViewModel(block: makeBlock()) { _ in
            attempts.count += 1
            if attempts.count == 1 { throw TestError.boom }
        }

        await sut.cancel()
        XCTAssertEqual(sut.localStatus, .failed)
        XCTAssertTrue(sut.isRetryable)
        XCTAssertEqual(sut.error, TestError.boom.localizedDescription)

        await sut.cancel()
        XCTAssertEqual(sut.localStatus, .cancelled)
        XCTAssertNil(sut.error)
        XCTAssertEqual(attempts.count, 2)
    }

    func test_cancel_whileInFlight_secondCallIsIgnored() async {
        let attempts = AttemptCounter()
        let gate = ContinuationBox()
        let sut = CancelOrderCardViewModel(block: makeBlock()) { _ in
            attempts.count += 1
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                gate.resume = { continuation.resume() }
            }
        }

        let inFlight = Task { await sut.cancel() }
        while attempts.count == 0 { await Task.yield() }
        XCTAssertTrue(sut.isCancelling)

        await sut.cancel()
        XCTAssertEqual(attempts.count, 1)

        gate.resume?()
        await inFlight.value
        XCTAssertEqual(sut.localStatus, .cancelled)
        XCTAssertEqual(attempts.count, 1)
    }

    func test_cancel_whenAlreadyCancelled_isNoOp() async {
        let attempts = AttemptCounter()
        let sut = CancelOrderCardViewModel(block: makeBlock(status: .cancelled)) { _ in
            attempts.count += 1
        }

        await sut.cancel()

        XCTAssertEqual(sut.localStatus, .cancelled)
        XCTAssertEqual(attempts.count, 0)
    }

    private enum TestError: LocalizedError {
        case boom
        var errorDescription: String? { "Network unavailable" }
    }

    @MainActor
    private final class OrderIdRecorder {
        var value: String?
    }

    @MainActor
    private final class AttemptCounter {
        var count = 0
    }

    @MainActor
    private final class ContinuationBox {
        var resume: (() -> Void)?
    }
}
