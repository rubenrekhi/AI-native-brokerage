import XCTest
@testable import Sevino

@MainActor
final class RadarViewModelTests: XCTestCase {

    private var mockService: MockRadarService!
    private var viewModel: RadarViewModel!

    override func setUp() {
        mockService = MockRadarService()
        viewModel = RadarViewModel(service: mockService)
    }

    // MARK: - Initial state

    func testInitialStateIsEmpty() {
        XCTAssertTrue(viewModel.radarItems.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - loadRadar success

    func testLoadRadarSuccessPopulatesItems() async {
        mockService.radarItems = [
            Self.makeItem(ticker: "NVDA", isStarred: false),
            Self.makeItem(ticker: "AAPL", isStarred: true),
        ]

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.radarItems.map(\.ticker), ["NVDA", "AAPL"])
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - Star toggle

    func testToggleStarFlipsStarredFlagOnMatchingItem() async {
        mockService.radarItems = [
            Self.makeItem(ticker: "NVDA", isStarred: false),
            Self.makeItem(ticker: "AAPL", isStarred: true),
        ]
        await viewModel.loadRadar()

        viewModel.toggleStar(for: "NVDA")

        XCTAssertEqual(viewModel.radarItems.first { $0.ticker == "NVDA" }?.isStarred, true)
        XCTAssertEqual(viewModel.radarItems.first { $0.ticker == "AAPL" }?.isStarred, true,
                       "toggling one item should not affect others")
    }

    func testToggleStarTwiceReturnsToOriginal() async {
        mockService.radarItems = [Self.makeItem(ticker: "NVDA", isStarred: false)]
        await viewModel.loadRadar()

        viewModel.toggleStar(for: "NVDA")
        viewModel.toggleStar(for: "NVDA")

        XCTAssertEqual(viewModel.radarItems.first?.isStarred, false)
    }

    func testToggleStarWithUnknownIdIsNoOp() async {
        mockService.radarItems = [Self.makeItem(ticker: "NVDA", isStarred: false)]
        await viewModel.loadRadar()

        viewModel.toggleStar(for: "DOES_NOT_EXIST")

        XCTAssertEqual(viewModel.radarItems.first?.isStarred, false)
    }

    func testLoadRadarOverwritesLocalStarToggles() async {
        mockService.radarItems = [Self.makeItem(ticker: "NVDA", isStarred: false)]
        await viewModel.loadRadar()
        viewModel.toggleStar(for: "NVDA")
        XCTAssertEqual(viewModel.radarItems.first?.isStarred, true)

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.radarItems.first?.isStarred, false,
                       "reload reflects server truth; local toggles are not persisted")
    }

    // MARK: - Error path

    func testLoadRadarFailureSurfacesError() async {
        mockService.fetchRadarError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.loadRadar()

        XCTAssertEqual(viewModel.error, "Network error")
        XCTAssertTrue(viewModel.radarItems.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockService.fetchRadarError = NSError(domain: "test", code: 0)
        await viewModel.loadRadar()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - Helpers

    private static func makeItem(ticker: String, isStarred: Bool) -> RadarItem {
        RadarItem(
            ticker: ticker,
            description: "desc",
            price: "$100.00", changePercent: "+1.00%", isPositive: true,
            expiresIn: "3 days", isStarred: isStarred
        )
    }
}
