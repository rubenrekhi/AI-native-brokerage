import XCTest
@testable import Sevino

@MainActor
final class HomeChatInputViewModelTests: XCTestCase {

    private var mention: TickerMentionViewModel!
    private var mockDictation: MockDictationController!
    private var sut: HomeChatInputViewModel!

    override func setUp() {
        super.setUp()
        mention = TickerMentionViewModel(service: MockAssetSearchService())
        mockDictation = MockDictationController()
        sut = HomeChatInputViewModel(mention: mention, dictation: mockDictation)
    }

    override func tearDown() {
        sut = nil
        mockDictation = nil
        mention = nil
        super.tearDown()
    }

    // MARK: - Toggle

    func testToggleStartsDictation_whenIdle() async {
        sut.toggleDictation()
        await Task.yield()

        XCTAssertEqual(mockDictation.startCallCount, 1)
        XCTAssertTrue(sut.isRecording)
    }

    func testToggleStopsDictation_whenRecording() async {
        sut.toggleDictation()
        await Task.yield()
        XCTAssertTrue(sut.isRecording)

        sut.toggleDictation()

        XCTAssertEqual(mockDictation.stopCallCount, 1)
        XCTAssertFalse(sut.isRecording)
    }

    // MARK: - Transcript merging

    func testTranscriptAppendsToBaseText_whileRecording() async {
        mention.updateText("hello")
        sut.toggleDictation()
        await Task.yield()

        mockDictation.transcript = "world"

        XCTAssertEqual(mention.text, "hello world")
    }

    func testTranscriptReplacesText_whenBaseIsEmpty() async {
        sut.toggleDictation()
        await Task.yield()

        mockDictation.transcript = "new message"

        XCTAssertEqual(mention.text, "new message")
    }

    func testTranscriptIgnored_whenNotRecording() {
        mention.updateText("untouched")

        mockDictation.transcript = "should not apply"

        XCTAssertEqual(mention.text, "untouched")
    }

    // MARK: - Status → alert routing

    func testPermissionDeniedStatus_raisesPermissionDeniedAlert() {
        mockDictation.status = .permissionDenied

        XCTAssertEqual(sut.alert, .permissionDenied)
    }

    func testUnavailableStatus_raisesUnavailableAlert() {
        mockDictation.status = .unavailable

        XCTAssertEqual(sut.alert, .unavailable)
    }

    func testFailedStatus_raisesFailedAlert() {
        mockDictation.status = .failed

        XCTAssertEqual(sut.alert, .failed)
    }

    func testIdleAndRecordingStatuses_doNotRaiseAlert() {
        mockDictation.status = .recording
        XCTAssertNil(sut.alert)

        mockDictation.status = .idle
        XCTAssertNil(sut.alert)
    }

    // MARK: - stopIfRecording

    func testStopIfRecordingCallsStop_whenRecording() async {
        sut.toggleDictation()
        await Task.yield()

        sut.stopIfRecording()

        XCTAssertEqual(mockDictation.stopCallCount, 1)
    }

    func testStopIfRecordingIsNoOp_whenIdle() {
        sut.stopIfRecording()

        XCTAssertEqual(mockDictation.stopCallCount, 0)
    }
}
