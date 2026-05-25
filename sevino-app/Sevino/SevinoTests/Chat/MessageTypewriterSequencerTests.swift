import XCTest
@testable import Sevino

@MainActor
final class MessageTypewriterSequencerTests: XCTestCase {

    func test_initialState_unlocksOrdinalZeroOnly() {
        let sut = MessageTypewriterSequencer()

        XCTAssertTrue(sut.isUnlocked(ordinal: 0))
        XCTAssertFalse(sut.isUnlocked(ordinal: 1))
        XCTAssertFalse(sut.isUnlocked(ordinal: 5))
    }

    func test_markCompleted_advancesUnlockedOrdinal() {
        let sut = MessageTypewriterSequencer()

        sut.markCompleted(ordinal: 0)

        XCTAssertTrue(sut.isUnlocked(ordinal: 0))
        XCTAssertTrue(sut.isUnlocked(ordinal: 1))
        XCTAssertFalse(sut.isUnlocked(ordinal: 2))
    }

    func test_markCompleted_isIdempotent() {
        let sut = MessageTypewriterSequencer()

        sut.markCompleted(ordinal: 0)
        sut.markCompleted(ordinal: 0)
        sut.markCompleted(ordinal: 0)

        // Repeated calls for the same ordinal don't skip ahead.
        XCTAssertTrue(sut.isUnlocked(ordinal: 1))
        XCTAssertFalse(sut.isUnlocked(ordinal: 2))
    }

    func test_markCompleted_monotonic_olderOrdinalIsNoOp() {
        let sut = MessageTypewriterSequencer()

        sut.markCompleted(ordinal: 2)
        XCTAssertTrue(sut.isUnlocked(ordinal: 3))

        // A late markCompleted(0) must not roll the gate back.
        sut.markCompleted(ordinal: 0)

        XCTAssertTrue(sut.isUnlocked(ordinal: 3))
        XCTAssertFalse(sut.isUnlocked(ordinal: 4))
    }

    func test_markCompleted_sequentialAdvancesByOne() {
        let sut = MessageTypewriterSequencer()

        sut.markCompleted(ordinal: 0)
        sut.markCompleted(ordinal: 1)
        sut.markCompleted(ordinal: 2)

        XCTAssertTrue(sut.isUnlocked(ordinal: 3))
        XCTAssertFalse(sut.isUnlocked(ordinal: 4))
    }
}
