import XCTest
@testable import Sevino

@MainActor
final class ShortcutsOverflowSheetTests: XCTestCase {

    func testSelectingShortcutForwardsItsText() {
        var received: [String] = []
        let shortcuts = Self.makeShortcuts(count: 4)
        let sheet = ShortcutsOverflowSheet(
            scale: 1,
            shortcuts: shortcuts,
            onSelect: { received.append($0) }
        )

        sheet.select(shortcuts[2])

        XCTAssertEqual(received, ["s2"])
    }

    private static func makeShortcuts(count: Int) -> [Shortcut] {
        (0..<count).map { Shortcut(id: UUID(), text: "s\($0)", category: .capability) }
    }
}
