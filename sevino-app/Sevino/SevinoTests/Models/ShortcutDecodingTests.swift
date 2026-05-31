import XCTest
@testable import Sevino

/**
 Wire-contract tests for `Shortcut` (SEV-622 / S5).

 The reference JSON mirrors `sevino-api/app/schemas/shortcuts.py`. The feed
 decoder swallows errors silently (`ShortcutsViewModel.load` falls back to an
 empty list), so a category raw-value or envelope-shape regression would render
 zero shortcuts at runtime with no error. These tests fail loudly instead. The
 wire format is hand-mirrored with no codegen — if the backend schema changes,
 this file must change in lockstep.
 */
final class ShortcutDecodingTests: XCTestCase {

    func testDecodesEnvelopeAndAllCategories() throws {
        let json = Data("""
        {
          "items": [
            {"id": "5e9d3c1f-7a4b-4c2e-9f8a-1b2c3d4e5f60", "text": "How does Sevino work?", "category": "first_time"},
            {"id": "11111111-1111-1111-1111-111111111111", "text": "Is having 32% in NVDA too much?", "category": "portfolio_state"},
            {"id": "22222222-2222-2222-2222-222222222222", "text": "Why is the market down today?", "category": "market_state"},
            {"id": "33333333-3333-3333-3333-333333333333", "text": "What's on Radar today?", "category": "radar_update"},
            {"id": "44444444-4444-4444-4444-444444444444", "text": "Compare AAPL and MSFT", "category": "capability"},
            {"id": "55555555-5555-5555-5555-555555555555", "text": "What's diversification?", "category": "quiet_state"}
          ]
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(ShortcutsEnvelope.self, from: json)

        XCTAssertEqual(
            decoded.items.map(\.category),
            [.firstTime, .portfolioState, .marketState, .radarUpdate, .capability, .quietState]
        )
        XCTAssertEqual(decoded.items.first?.text, "How does Sevino work?")
        XCTAssertEqual(
            decoded.items.first?.id,
            UUID(uuidString: "5e9d3c1f-7a4b-4c2e-9f8a-1b2c3d4e5f60")
        )
    }

    func testUnknownCategoryFailsDecode() {
        let json = Data("""
        {"id": "5e9d3c1f-7a4b-4c2e-9f8a-1b2c3d4e5f60", "text": "x", "category": "weather"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Shortcut.self, from: json))
    }

    private struct ShortcutsEnvelope: Decodable {
        let items: [Shortcut]
    }
}
