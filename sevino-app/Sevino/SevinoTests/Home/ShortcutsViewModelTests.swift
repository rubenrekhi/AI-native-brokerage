import XCTest
@testable import Sevino

@MainActor
final class ShortcutsViewModelTests: XCTestCase {

    private var mockClient: MockShortcutsAPIClient!
    private var viewModel: ShortcutsViewModel!

    override func setUp() {
        mockClient = MockShortcutsAPIClient()
        viewModel = ShortcutsViewModel(client: mockClient)
    }

    // MARK: - Initial state

    func testInitialStateIsEmpty() {
        XCTAssertTrue(viewModel.shortcuts.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertTrue(viewModel.topShortcuts.isEmpty)
        XCTAssertTrue(viewModel.overflowShortcuts.isEmpty)
        XCTAssertFalse(viewModel.hasOverflow)
    }

    // MARK: - load()

    func testLoadPopulatesShortcutsFromClient() async {
        mockClient.shortcutsToReturn = Self.makeShortcuts(count: 5)

        await viewModel.load()

        XCTAssertEqual(viewModel.shortcuts.count, 5)
        XCTAssertEqual(mockClient.fetchShortcutsCallCount, 1)
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - Slicing

    func testTopShortcutsReturnsFirstThree() async {
        mockClient.shortcutsToReturn = Self.makeShortcuts(count: 5)
        await viewModel.load()

        XCTAssertEqual(viewModel.topShortcuts.map(\.text), ["s0", "s1", "s2"])
    }

    func testOverflowShortcutsReturnsRemainder() async {
        mockClient.shortcutsToReturn = Self.makeShortcuts(count: 5)
        await viewModel.load()

        XCTAssertEqual(viewModel.overflowShortcuts.map(\.text), ["s3", "s4"])
    }

    // MARK: - hasOverflow boundary

    func testHasOverflowIsFalseAtThreeItems() async {
        mockClient.shortcutsToReturn = Self.makeShortcuts(count: 3)
        await viewModel.load()

        XCTAssertFalse(viewModel.hasOverflow)
        XCTAssertEqual(viewModel.topShortcuts.count, 3)
        XCTAssertTrue(viewModel.overflowShortcuts.isEmpty)
    }

    func testHasOverflowIsTrueAtFourItems() async {
        mockClient.shortcutsToReturn = Self.makeShortcuts(count: 4)
        await viewModel.load()

        XCTAssertTrue(viewModel.hasOverflow)
        XCTAssertEqual(viewModel.overflowShortcuts.count, 1)
    }

    // MARK: - Failure path

    func testLoadFailureYieldsEmptyShortcuts() async {
        mockClient.shortcutsToReturn = Self.makeShortcuts(count: 5)
        await viewModel.load()
        XCTAssertFalse(viewModel.shortcuts.isEmpty)

        mockClient.fetchError = URLError(.notConnectedToInternet)
        await viewModel.load()

        XCTAssertTrue(viewModel.shortcuts.isEmpty)
        XCTAssertFalse(viewModel.isLoading)
    }

    // MARK: - Helpers

    private static func makeShortcuts(count: Int) -> [Shortcut] {
        (0..<count).map { index in
            Shortcut(id: UUID(), text: "s\(index)", category: .capability)
        }
    }
}
