import XCTest
@testable import Sevino

@MainActor
final class RadarViewModelTabsTests: XCTestCase {

    private var mockClient: MockRadarAPIClient!
    private var viewModel: RadarViewModel!

    override func setUp() {
        mockClient = MockRadarAPIClient()
        viewModel = RadarViewModel(client: mockClient)
    }

    func testNewAndStarredSplitByFavoriteAndSource() async {
        mockClient.fetchResponse = RadarListResponse(
            items: [
                Self.makeItem(ticker: "NVDA", source: .aiGenerated, isStarred: false),
                Self.makeItem(ticker: "AAPL", source: .aiGenerated, isStarred: true),
                Self.makeItem(ticker: "TSLA", source: .userAdded, isStarred: true),
                Self.makeItem(ticker: "MSFT", source: .aiGenerated, isStarred: false),
            ],
            nextRefreshAt: nil
        )

        await viewModel.loadRadar()

        XCTAssertEqual(Set(viewModel.newItems.map(\.ticker)), ["NVDA", "MSFT"])
        XCTAssertEqual(Set(viewModel.starredItems.map(\.ticker)), ["AAPL", "TSLA"])
    }

    func testUserAddedUnstarredAppearsInNeitherTab() async {
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(ticker: "GME", source: .userAdded, isStarred: false)],
            nextRefreshAt: nil
        )

        await viewModel.loadRadar()

        XCTAssertTrue(viewModel.newItems.isEmpty)
        XCTAssertTrue(viewModel.starredItems.isEmpty)
    }

    func testNewItemsSortedByRelevanceDescending() async {
        mockClient.fetchResponse = RadarListResponse(
            items: [
                Self.makeItem(ticker: "LOW", isStarred: false, relevanceScore: 0.2),
                Self.makeItem(ticker: "HIGH", isStarred: false, relevanceScore: 0.9),
                Self.makeItem(ticker: "MID", isStarred: false, relevanceScore: 0.5),
            ],
            nextRefreshAt: nil
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.newItems.map(\.ticker), ["HIGH", "MID", "LOW"])
    }

    func testStarredItemsSortedByCreatedAtDescending() async {
        let old = Date(timeIntervalSince1970: 1_000)
        let mid = Date(timeIntervalSince1970: 2_000)
        let new = Date(timeIntervalSince1970: 3_000)
        mockClient.fetchResponse = RadarListResponse(
            items: [
                Self.makeItem(ticker: "OLD", isStarred: true, createdAt: old),
                Self.makeItem(ticker: "NEW", isStarred: true, createdAt: new),
                Self.makeItem(ticker: "MID", isStarred: true, createdAt: mid),
            ],
            nextRefreshAt: nil
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.starredItems.map(\.ticker), ["NEW", "MID", "OLD"])
    }

    func testStarringAIItemMovesItFromNewToStarred() async {
        let id = UUID()
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(id: id, ticker: "NVDA", source: .aiGenerated, isStarred: false)],
            nextRefreshAt: nil
        )
        await viewModel.loadRadar()
        XCTAssertEqual(viewModel.newItems.map(\.ticker), ["NVDA"])
        XCTAssertTrue(viewModel.starredItems.isEmpty)

        mockClient.toggleResult = Self.makeItem(id: id, ticker: "NVDA", isStarred: true)
        await viewModel.toggleStar(itemId: id)

        XCTAssertTrue(viewModel.newItems.isEmpty)
        XCTAssertEqual(viewModel.starredItems.map(\.ticker), ["NVDA"])
    }

    func testDefaultTabIsNewWhenNewItemsExist() async {
        viewModel.activeTab = .starred
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(ticker: "NVDA", source: .aiGenerated, isStarred: false)],
            nextRefreshAt: nil
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.activeTab, .new)
    }

    func testDefaultTabIsStarredWhenNoNewItems() async {
        viewModel.activeTab = .new
        mockClient.fetchResponse = RadarListResponse(
            items: [Self.makeItem(ticker: "AAPL", source: .aiGenerated, isStarred: true)],
            nextRefreshAt: nil
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.activeTab, .starred)
    }

    func testDefaultTabIsStarredWhenEmpty() async {
        viewModel.activeTab = .new
        mockClient.fetchResponse = RadarListResponse(items: [], nextRefreshAt: nil)

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.activeTab, .starred)
    }

    func testNextRefreshWeekdayFormatsFutureAnchor() async {
        let future = Date(timeIntervalSinceNow: 7 * 86_400)
        mockClient.fetchResponse = RadarListResponse(items: [], nextRefreshAt: future)

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.nextRefreshWeekday, future.formatted(.dateTime.weekday(.wide)))
    }

    func testNextRefreshWeekdayIsNilForPastAnchor() async {
        let past = Date(timeIntervalSinceNow: -7 * 86_400)
        mockClient.fetchResponse = RadarListResponse(items: [], nextRefreshAt: past)

        await viewModel.loadRadar()

        XCTAssertNil(viewModel.nextRefreshWeekday)
    }

    func testNextRefreshWeekdayIsNilWhenAnchorMissing() async {
        mockClient.fetchResponse = RadarListResponse(items: [], nextRefreshAt: nil)

        await viewModel.loadRadar()

        XCTAssertNil(viewModel.nextRefreshWeekday)
    }

    private static func makeItem(
        id: UUID = UUID(),
        ticker: String,
        source: RadarSource = .aiGenerated,
        isStarred: Bool,
        relevanceScore: Float? = nil,
        createdAt: Date = Date()
    ) -> RadarItem {
        RadarItem(
            id: id,
            ticker: ticker,
            description: "desc",
            source: source,
            relevanceScore: relevanceScore,
            createdAt: createdAt,
            isStarred: isStarred,
            price: "$100.00",
            changePercent: "+1.00%",
            isPositive: true,
            expiresIn: "3 days"
        )
    }
}
