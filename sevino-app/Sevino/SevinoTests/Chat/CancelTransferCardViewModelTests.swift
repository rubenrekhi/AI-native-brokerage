import XCTest
@testable import Sevino

@MainActor
final class CancelTransferCardViewModelTests: XCTestCase {

    private func makeBlock(status: TransferStatus = .pending) -> CancelTransferBlock {
        CancelTransferBlock(
            blockId: "blk_1",
            transferId: "trf_1",
            direction: .deposit,
            amount: 500,
            bankName: "Chase",
            bankMask: "1234",
            initiatedAt: Date(timeIntervalSince1970: 1_700_000_000),
            status: status
        )
    }

    func test_cancel_happyPath_setsCancelled() async {
        let recorder = CancelRecorder()
        let sut = CancelTransferCardViewModel(block: makeBlock()) { transferId in
            recorder.capturedTransferId = transferId
        }

        await sut.cancel()

        XCTAssertEqual(recorder.capturedTransferId, "trf_1")
        XCTAssertEqual(sut.localStatus, .cancelled)
        XCTAssertFalse(sut.isCancelling)
        XCTAssertNil(sut.error)
    }

    func test_cancel_notCancellableError_setsFailedAndSurfacesError() async {
        let sut = CancelTransferCardViewModel(block: makeBlock()) { _ in
            throw TransferCancellationError.notCancellable
        }

        await sut.cancel()

        XCTAssertEqual(sut.localStatus, .failed)
        XCTAssertNotNil(sut.error)
        XCTAssertFalse(sut.isCancelling)
    }

    func test_cancel_genericError_staysPendingAndSurfacesError() async {
        let sut = CancelTransferCardViewModel(block: makeBlock()) { _ in
            throw TestError.boom
        }

        await sut.cancel()

        XCTAssertEqual(sut.localStatus, .pending)
        XCTAssertEqual(sut.error, TestError.boom.localizedDescription)
        XCTAssertFalse(sut.isCancelling)
    }

    func test_cancel_whenAlreadyCancelled_isNoOp() async {
        let recorder = CancelRecorder()
        let sut = CancelTransferCardViewModel(block: makeBlock(status: .cancelled)) { _ in
            recorder.callCount += 1
        }

        await sut.cancel()

        XCTAssertEqual(recorder.callCount, 0)
        XCTAssertEqual(sut.localStatus, .cancelled)
    }

    func test_cancel_retryAfterGenericError_canSucceed() async {
        let recorder = CancelRecorder()
        let sut = CancelTransferCardViewModel(block: makeBlock()) { _ in
            recorder.callCount += 1
            if recorder.callCount == 1 { throw TestError.boom }
        }

        await sut.cancel()
        XCTAssertEqual(sut.localStatus, .pending)
        XCTAssertNotNil(sut.error)

        await sut.cancel()
        XCTAssertEqual(sut.localStatus, .cancelled)
        XCTAssertNil(sut.error)
        XCTAssertEqual(recorder.callCount, 2)
    }

    @MainActor
    private final class CancelRecorder {
        var capturedTransferId: String?
        var callCount = 0
    }

    private enum TestError: LocalizedError {
        case boom
        var errorDescription: String? { "boom" }
    }
}
