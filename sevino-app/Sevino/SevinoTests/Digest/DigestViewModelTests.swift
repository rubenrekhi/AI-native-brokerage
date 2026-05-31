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

    func testCurrentChatDigestCardCapturesCardInView() async throws {
        let firstCard = makeCard(symbol: "AAPL")
        let secondCard = makeCard(symbol: "MSFT")
        client.todayResponse = makeResponse(cards: [firstCard, secondCard], dismissedAt: nil)
        await viewModel.refreshForForeground()
        XCTAssertTrue(viewModel.showNextCard())

        let chatCard = try XCTUnwrap(viewModel.currentChatDigestCard())

        XCTAssertEqual(chatCard.payload["id"], .string(secondCard.id.uuidString))
        XCTAssertEqual(chatCard.payload["kind"], .string("market_context"))
        XCTAssertEqual(chatCard.payload["related_symbols"], .array([.string("MSFT")]))
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

    private func makeCard(symbol: String? = nil) -> DigestCard {
        .marketContext(MarketContextDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: symbol.map { [$0] } ?? [],
            cardContext: [:],
            direction: "mixed",
            sp500ChangePct: 0.004,
            nasdaqChangePct: -0.002,
            summary: "Mixed session"
        ))
    }
}
