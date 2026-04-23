import XCTest
@testable import Sevino

@MainActor
final class TickerMentionViewModelTests: XCTestCase {

    private var mockService: MockAssetSearchService!
    private var viewModel: TickerMentionViewModel!

    private static let debounce: Duration = .milliseconds(10)
    private static let postDebounceWait: UInt64 = 60_000_000 // 60ms in ns, well past debounce

    override func setUp() {
        mockService = MockAssetSearchService()
        mockService.defaultResults = [
            AssetSearchResult(symbol: "TSLA", name: "Tesla, Inc.", logoUrl: nil)
        ]
        viewModel = TickerMentionViewModel(service: mockService, debounceInterval: Self.debounce)
    }

    // MARK: - Trigger detection

    func testDollarPlusLetterActivatesSearchMode() async throws {
        viewModel.updateText("$T")
        XCTAssertEqual(viewModel.activeQuery, "T")

        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertTrue(viewModel.isShowingPopup)
        XCTAssertEqual(mockService.searchCallCount, 1)
        XCTAssertEqual(mockService.receivedQueries, ["T"])
    }

    func testDollarPlusDigitIsIgnored() async throws {
        viewModel.updateText("$20")
        XCTAssertNil(viewModel.activeQuery)

        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertFalse(viewModel.isShowingPopup)
        XCTAssertEqual(mockService.searchCallCount, 0)
    }

    func testDollarAloneDoesNotActivate() async throws {
        viewModel.updateText("Buy $")
        XCTAssertNil(viewModel.activeQuery)

        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertFalse(viewModel.isShowingPopup)
        XCTAssertEqual(mockService.searchCallCount, 0)
    }

    func testActiveQueryIsOnlyTrailingMention() {
        viewModel.updateText("$T and then some words")
        XCTAssertNil(viewModel.activeQuery)
    }

    // MARK: - Selection

    func testSelectResultInsertsTokenAndDismissesPopup() async throws {
        viewModel.updateText("$TSL")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertTrue(viewModel.isShowingPopup)

        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla, Inc.", logoUrl: nil))

        XCTAssertEqual(viewModel.text, "$TSLA")
        XCTAssertEqual(viewModel.tokens.count, 1)
        XCTAssertEqual(viewModel.tokens.first?.symbol, "TSLA")
        XCTAssertEqual(viewModel.tokens.first?.range, 0..<5)
        XCTAssertNil(viewModel.activeQuery)
        XCTAssertFalse(viewModel.isShowingPopup)
        XCTAssertTrue(viewModel.results.isEmpty)
    }

    func testSelectResultReplacesQueryInPlaceWithSurroundingText() async throws {
        viewModel.updateText("Buy $TS")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)

        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla, Inc.", logoUrl: nil))

        XCTAssertEqual(viewModel.text, "Buy $TSLA")
        XCTAssertEqual(viewModel.tokens.first?.range, 4..<9)
    }

    // MARK: - Space completion

    func testSpaceAfterValidTickerCommitsToken() {
        viewModel.updateText("$TSLA")
        viewModel.updateText("$TSLA ")

        XCTAssertEqual(viewModel.tokens.count, 1)
        XCTAssertEqual(viewModel.tokens.first?.symbol, "TSLA")
        XCTAssertEqual(viewModel.tokens.first?.range, 0..<5)
    }

    func testSpaceAfterLowercaseDoesNotCommit() {
        viewModel.updateText("$tsla")
        viewModel.updateText("$tsla ")

        XCTAssertTrue(viewModel.tokens.isEmpty)
    }

    func testSpaceAfterTooLongQueryDoesNotCommit() {
        viewModel.updateText("$ABCDEF")
        viewModel.updateText("$ABCDEF ")

        XCTAssertTrue(viewModel.tokens.isEmpty)
    }

    // MARK: - Dismissal

    func testDeletingPastDollarDismissesPopup() async throws {
        viewModel.updateText("$T")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertTrue(viewModel.isShowingPopup)

        viewModel.updateText("$")
        XCTAssertNil(viewModel.activeQuery)
        XCTAssertFalse(viewModel.isShowingPopup)

        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertTrue(viewModel.results.isEmpty)
    }

    func testDismissClearsStateAndCancelsSearch() async throws {
        viewModel.updateText("$T")
        viewModel.dismiss()

        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertNil(viewModel.activeQuery)
        XCTAssertTrue(viewModel.results.isEmpty)
        XCTAssertFalse(viewModel.isShowingPopup)
    }

    // MARK: - Debounce

    func testRapidTypingFiresOnlyOneSearch() async throws {
        viewModel.updateText("$T")
        viewModel.updateText("$TS")
        viewModel.updateText("$TSL")
        viewModel.updateText("$TSLA")

        try await Task.sleep(nanoseconds: Self.postDebounceWait)

        XCTAssertEqual(mockService.searchCallCount, 1)
        XCTAssertEqual(mockService.receivedQueries, ["TSLA"])
    }

    func testStaleResultsDoNotOverwriteNewerQuery() async throws {
        // Each `search` call blocks briefly so the first request's results arrive after
        // the second request has already updated `activeQuery`. Guard must drop stale results.
        actor Gate {
            var continuations: [CheckedContinuation<Void, Never>] = []
            func wait() async {
                await withCheckedContinuation { continuations.append($0) }
            }
            func release() {
                continuations.forEach { $0.resume() }
                continuations.removeAll()
            }
        }
        let gate = Gate()

        final class GatedService: AssetSearchServiceProtocol, @unchecked Sendable {
            let gate: Gate
            let responses: [String: [AssetSearchResult]]
            init(gate: Gate, responses: [String: [AssetSearchResult]]) {
                self.gate = gate
                self.responses = responses
            }
            func search(query: String, limit: Int) async throws -> [AssetSearchResult] {
                await gate.wait()
                return responses[query] ?? []
            }
        }

        let gatedService = GatedService(
            gate: gate,
            responses: [
                "TS": [AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil)],
                "TSLA": [AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil)],
            ]
        )
        viewModel = TickerMentionViewModel(service: gatedService, debounceInterval: .milliseconds(1))

        viewModel.updateText("$TS")
        try await Task.sleep(nanoseconds: 20_000_000)
        viewModel.updateText("$TSLA")
        try await Task.sleep(nanoseconds: 20_000_000)

        await gate.release()
        try await Task.sleep(nanoseconds: 30_000_000)

        XCTAssertEqual(viewModel.activeQuery, "TSLA")
        XCTAssertEqual(viewModel.results.map(\.symbol), ["TSLA"])
    }

    // MARK: - Multiple tokens

    func testMultipleTokensTrackedInArray() async throws {
        viewModel.updateText("$TSL")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil))

        viewModel.updateText("$TSLA and $AM")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "AMD", name: "Advanced Micro Devices", logoUrl: nil))

        XCTAssertEqual(viewModel.text, "$TSLA and $AMD")
        XCTAssertEqual(viewModel.tokens.map(\.symbol), ["TSLA", "AMD"])
        XCTAssertEqual(viewModel.tokens.map(\.range), [0..<5, 10..<14])
    }

    // MARK: - Token removal

    func testRemoveTokenDeletesTokenAndText() {
        viewModel.updateText("$TSLA")
        viewModel.updateText("$TSLA ")
        XCTAssertEqual(viewModel.tokens.count, 1)
        let tokenId = viewModel.tokens[0].id

        viewModel.removeToken(id: tokenId)

        XCTAssertEqual(viewModel.text, " ")
        XCTAssertTrue(viewModel.tokens.isEmpty)
    }

    func testRemoveTokenShiftsTrailingTokenRanges() async throws {
        viewModel.updateText("$TSL")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil))

        viewModel.updateText("$TSLA $AM")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "AMD", name: "AMD", logoUrl: nil))

        let firstId = viewModel.tokens[0].id
        viewModel.removeToken(id: firstId)

        XCTAssertEqual(viewModel.text, " $AMD")
        XCTAssertEqual(viewModel.tokens.map(\.symbol), ["AMD"])
        XCTAssertEqual(viewModel.tokens.map(\.range), [1..<5])
    }

    func testEditingTokenCharactersDropsIt() async throws {
        viewModel.updateText("$TSL")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil))

        // User edits inside the token, breaking the `$TSLA` literal.
        viewModel.updateText("$TSLX")

        XCTAssertTrue(viewModel.tokens.isEmpty)
    }

    // MARK: - Message segments

    func testMakeSegmentsEmptyTextReturnsEmpty() {
        XCTAssertTrue(viewModel.makeSegments().isEmpty)
    }

    func testMakeSegmentsPlainTextWithoutTokensReturnsSingleTextSegment() {
        viewModel.updateText("How is my portfolio?")
        XCTAssertEqual(viewModel.makeSegments(), [.text("How is my portfolio?")])
    }

    func testMakeSegmentsSingleTokenSplitsSurroundingText() {
        viewModel.updateText("$TSLA")
        viewModel.updateText("$TSLA ")  // commit via space
        viewModel.updateText("$TSLA up")

        XCTAssertEqual(viewModel.makeSegments(), [
            .ticker("TSLA"),
            .text(" up"),
        ])
    }

    func testMakeSegmentsLeadingAndTrailingText() async throws {
        viewModel.updateText("Buy $TS")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil))
        viewModel.updateText("Buy $TSLA now")

        XCTAssertEqual(viewModel.makeSegments(), [
            .text("Buy "),
            .ticker("TSLA"),
            .text(" now"),
        ])
    }

    func testMakeSegmentsMultipleTokens() async throws {
        viewModel.updateText("$TSL")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil))
        viewModel.updateText("$TSLA and $AM")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "AMD", name: "AMD", logoUrl: nil))

        XCTAssertEqual(viewModel.makeSegments(), [
            .ticker("TSLA"),
            .text(" and "),
            .ticker("AMD"),
        ])
    }

    // MARK: - Clear

    func testClearResetsEverything() async throws {
        viewModel.updateText("$TSL")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        viewModel.selectResult(AssetSearchResult(symbol: "TSLA", name: "Tesla", logoUrl: nil))
        viewModel.updateText("$TSLA plus $A")
        try await Task.sleep(nanoseconds: Self.postDebounceWait)
        XCTAssertFalse(viewModel.text.isEmpty)
        XCTAssertFalse(viewModel.tokens.isEmpty)

        viewModel.clear()

        XCTAssertTrue(viewModel.text.isEmpty)
        XCTAssertTrue(viewModel.tokens.isEmpty)
        XCTAssertTrue(viewModel.results.isEmpty)
        XCTAssertNil(viewModel.activeQuery)
        XCTAssertFalse(viewModel.isShowingPopup)
    }
}
