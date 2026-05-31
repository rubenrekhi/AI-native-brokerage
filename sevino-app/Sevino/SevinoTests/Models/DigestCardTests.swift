import XCTest
@testable import Sevino

final class DigestCardTests: XCTestCase {

    func testRoundTripsNestedPayload() throws {
        let card = ChatDigestCard(
            payload: [
                "id": .string("digest-1"),
                "kind": .string("big_move"),
                "relatedSymbols": .array([.string("AMD"), .string("NVDA")]),
                "card_context": .object([
                    "headline": .string("AMD moved 5%"),
                    "rank": .int(1),
                    "isActionable": .bool(true),
                    "details": .array([
                        .object(["label": .string("volume"), "value": .double(1.5)]),
                        .null,
                    ]),
                ]),
            ]
        )

        let data = try JSONEncoder().encode(card)
        let decoded = try JSONDecoder().decode(ChatDigestCard.self, from: data)

        XCTAssertEqual(decoded, card)
    }

    func testIdKindInitializerOverlaysFields() {
        let card = ChatDigestCard(
            id: "canonical-id",
            kind: "canonical-kind",
            fields: [
                "id": .string("field-id"),
                "kind": .string("field-kind"),
                "headline": .string("AMD moved 5%"),
            ]
        )

        XCTAssertEqual(card.payload["id"], .string("canonical-id"))
        XCTAssertEqual(card.payload["kind"], .string("canonical-kind"))
        XCTAssertEqual(card.payload["headline"], .string("AMD moved 5%"))
    }

    func testBuildsFromConcreteDigestCardWithSnakeCaseFields() throws {
        let id = UUID()
        let digestCard = DigestCard.upcomingEarnings(UpcomingEarningsDigestCard(
            id: id,
            priority: 4,
            relatedSymbols: ["AAPL"],
            cardContext: ["source": .string("test")],
            symbol: "AAPL",
            name: "Apple",
            reportsAt: Date(timeIntervalSince1970: 1_780_000_000),
            relativeLabel: "tomorrow"
        ))

        let chatCard = try ChatDigestCard(digestCard: digestCard)

        XCTAssertEqual(chatCard.payload["id"], .string(id.uuidString))
        XCTAssertEqual(chatCard.payload["kind"], .string("upcoming_earnings"))
        XCTAssertEqual(chatCard.payload["related_symbols"], .array([.string("AAPL")]))
        XCTAssertNotNil(chatCard.payload["reports_at"])
    }

    func testCardContextSourceFormatsEarningsChipText() {
        let card = ChatDigestCard(
            id: "digest-1",
            kind: "earnings_result",
            fields: ["related_symbols": .array([.string("AAPL")])]
        )

        let source = CardContextSource(digestCard: card)

        XCTAssertEqual(source?.displayText, "from your AAPL earnings card")
    }
}
