import XCTest
@testable import Sevino

@MainActor
final class DigestViewModelTests: XCTestCase {
    private var client: MockDigestAPIClient!
    private var viewModel: DigestViewModel!

    override func setUp() {
        client = MockDigestAPIClient()
        viewModel = DigestViewModel(client: client)
    }

    func testRefreshWithNoDigestHidesSurface() async {
        client.todayResponse = nil

        await viewModel.refreshForForeground()

        XCTAssertEqual(viewModel.presentationState, .hidden)
        XCTAssertTrue(viewModel.cards.isEmpty)
    }

    func testRefreshWithEmptyDigestHidesSurface() async {
        client.todayResponse = makeResponse(cards: [], dismissedAt: nil)

        await viewModel.refreshForForeground()

        XCTAssertEqual(viewModel.presentationState, .hidden)
        XCTAssertTrue(viewModel.cards.isEmpty)
    }

    func testRefreshWithUndismissedDigestPresentsFullScreen() async {
        client.todayResponse = makeResponse(cards: [makeCard()], dismissedAt: nil)

        await viewModel.refreshForForeground()

        XCTAssertEqual(viewModel.presentationState, .full)
        XCTAssertEqual(viewModel.cards.count, 1)
    }

    func testRefreshWithDismissedDigestShowsPeek() async {
        client.todayResponse = makeResponse(cards: [makeCard()], dismissedAt: Date())

        await viewModel.refreshForForeground()

        XCTAssertEqual(viewModel.presentationState, .peek)
    }

    func testSwipeNavigationAdvancesAndStopsPastLastCard() async {
        client.todayResponse = makeResponse(cards: [makeCard(), makeCard()], dismissedAt: nil)
        await viewModel.refreshForForeground()

        XCTAssertTrue(viewModel.showNextCard())
        XCTAssertEqual(viewModel.currentCardIndex, 1)
        XCTAssertFalse(viewModel.showNextCard())
        XCTAssertEqual(viewModel.currentCardIndex, 1)

        viewModel.showPreviousCard()
        XCTAssertEqual(viewModel.currentCardIndex, 0)
    }

    func testDismissMovesToPeekAndCallsAPI() async {
        client.todayResponse = makeResponse(cards: [makeCard()], dismissedAt: nil)
        await viewModel.refreshForForeground()

        await viewModel.dismissToPeek()

        XCTAssertEqual(viewModel.presentationState, .peek)
        XCTAssertEqual(viewModel.currentCardIndex, 0)
        XCTAssertEqual(client.dismissDigestCallCount, 1)
    }

    private func makeResponse(cards: [DigestCard], dismissedAt: Date?) -> DigestTodayResponseDTO {
        DigestTodayResponseDTO(
            snapshot: DigestSnapshotDTO(
                id: UUID(),
                nyLocalDate: "2026-05-31",
                cards: cards,
                generatedAt: Date(),
                dismissedAt: dismissedAt,
                createdAt: Date()
            ),
            peekVisible: dismissedAt != nil
        )
    }

    private func makeCard() -> DigestCard {
        .marketContext(MarketContextDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: [],
            cardContext: [:],
            direction: "mixed",
            sp500ChangePct: 0.004,
            nasdaqChangePct: -0.002,
            summary: "Mixed session"
        ))
    }
}
