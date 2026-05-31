import XCTest
@testable import Sevino

final class DividendStatusKindTests: XCTestCase {

    func test_from_executedReturnsSettled() {
        XCTAssertEqual(DividendStatusKind.from("executed"), .settled)
    }

    func test_from_correctReturnsSettled() {
        XCTAssertEqual(DividendStatusKind.from("correct"), .settled)
    }

    func test_from_canceledReturnsFailed() {
        XCTAssertEqual(DividendStatusKind.from("canceled"), .failed)
    }

    func test_from_cancelledReturnsFailed() {
        XCTAssertEqual(DividendStatusKind.from("cancelled"), .failed)
    }

    func test_from_isCaseInsensitive() {
        XCTAssertEqual(DividendStatusKind.from("EXECUTED"), .settled)
        XCTAssertEqual(DividendStatusKind.from("Canceled"), .failed)
    }

    func test_from_unrecognizedStatusReturnsUnknown() {
        XCTAssertEqual(DividendStatusKind.from(""), .unknown)
        XCTAssertEqual(DividendStatusKind.from("settled"), .unknown)
        XCTAssertEqual(DividendStatusKind.from("pending"), .unknown)
    }
}
