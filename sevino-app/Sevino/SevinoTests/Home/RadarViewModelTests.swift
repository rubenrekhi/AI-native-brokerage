import XCTest
@testable import Sevino

@MainActor
final class RadarViewModelTests: XCTestCase {

    private var mockClient: MockRadarAPIClient!
    private var viewModel: RadarViewModel!

    override func setUp() {
        mockClient = MockRadarAPIClient()
        viewModel = RadarViewModel(client: mockClient)
    }

    // MARK: - Initial state

    func testInitialStateIsEmpty() {
        XCTAssertTrue(viewModel.radarItems.isEmpty)
        XCTAssertNil(viewModel.nextRefreshAt)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - loadRadar

    func testLoadRadarPopulatesItemsAndNextRefreshAt() async {
        let refreshAt = Date(timeIntervalSince1970: 1_750_000_000)
        mockClient.fetchResponse = RadarListResponse(
            items: [
                Self.makeItem(ticker: "NVDA", isStarred: false),
                Self.makeItem(ticker: "AAPL", isStarred: true),
            ],
            nextRefreshAt: refreshAt
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.radarItems.map(\.ticker), ["NVDA", "AAPL"])
        XCTAssertEqual(viewModel.nextRefreshAt, refreshAt)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testLoadRadarFailureSurfacesErrorAndLeavesItemsUnchanged() async {
        mockClient.fetchError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.error, "Network error")
        XCTAssertTrue(viewModel.radarItems.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - toggleStar (200 path)

    func testToggleStarOnAIItemSendsPatchWithFavoriteTrue() async {
        let id = UUID()
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(id: id, ticker: "NVDA", source: .aiGenerated, isStarred: false)],
            nextRefreshAt: nil
        )
        await viewModel.loadRadar()
        mockClient.toggleResult = Self.makeItem(id: id, ticker: "NVDA", isStarred: true)

        await viewModel.toggleStar(itemId: id)

        XCTAssertEqual(mockClient.toggleCalls.count, 1)
        XCTAssertEqual(mockClient.toggleCalls.first?.itemId, id)
        XCTAssertEqual(mockClient.toggleCalls.first?.isFavorited, true)
        XCTAssertEqual(viewModel.radarItems.first?.isStarred, true)
        XCTAssertNil(viewModel.error)
    }

    func testToggleStarOnStarredItemSendsPatchWithFavoriteFalse() async {
        let id = UUID()
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(id: id, ticker: "AAPL", source: .aiGenerated, isStarred: true)],
            nextRefreshAt: nil
        )
        await viewModel.loadRadar()
        mockClient.toggleResult = Self.makeItem(id: id, ticker: "AAPL", isStarred: false)

        await viewModel.toggleStar(itemId: id)

        XCTAssertEqual(mockClient.toggleCalls.first?.isFavorited, false)
        XCTAssertEqual(viewModel.radarItems.first?.isStarred, false)
    }

    // MARK: - toggleStar (204 path)

    func testToggleStarReturning204RemovesItemLocally() async {
        let userId = UUID()
        let aiId = UUID()
        mockClient.fetchResponse = RadarListResponse(
            items: [
                Self.makeItem(id: userId, ticker: "TSLA", source: .userAdded, isStarred: true),
                Self.makeItem(id: aiId, ticker: "NVDA", source: .aiGenerated, isStarred: false),
            ],
            nextRefreshAt: nil
        )
        await viewModel.loadRadar()
        mockClient.toggleResult = .some(nil)  // 204 — server deleted the row

        await viewModel.toggleStar(itemId: userId)

        XCTAssertEqual(mockClient.toggleCalls.first?.isFavorited, false)
        XCTAssertEqual(viewModel.radarItems.map(\.ticker), ["NVDA"])
        XCTAssertNil(viewModel.error)
    }

    // MARK: - toggleStar edge cases

    func testToggleStarWithUnknownIdIsNoOp() async {
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(ticker: "NVDA", isStarred: false)],
            nextRefreshAt: nil
        )
        await viewModel.loadRadar()

        await viewModel.toggleStar(itemId: UUID())

        XCTAssertTrue(mockClient.toggleCalls.isEmpty)
        XCTAssertEqual(viewModel.radarItems.first?.isStarred, false)
    }

    func testToggleStarFailureSurfacesErrorAndLeavesItemUnchanged() async {
        let id = UUID()
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(id: id, ticker: "NVDA", isStarred: false)],
            nextRefreshAt: nil
        )
        await viewModel.loadRadar()
        mockClient.toggleError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "PATCH failed"]
        )

        await viewModel.toggleStar(itemId: id)

        XCTAssertEqual(viewModel.error, "PATCH failed")
        XCTAssertEqual(viewModel.radarItems.first?.isStarred, false)
    }

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockClient.fetchError = NSError(domain: "test", code: 0)
        await viewModel.loadRadar()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - Helpers

    private static func makeItem(
        id: UUID = UUID(),
        ticker: String,
        source: RadarSource = .aiGenerated,
        isStarred: Bool
    ) -> RadarItem {
        RadarItem(
            id: id,
            ticker: ticker,
            description: "desc",
            source: source,
            isStarred: isStarred,
            price: "$100.00",
            changePercent: "+1.00%",
            isPositive: true,
            expiresIn: "3 days"
        )
    }
}
