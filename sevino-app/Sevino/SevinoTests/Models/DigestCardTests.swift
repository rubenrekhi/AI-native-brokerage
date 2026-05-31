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
}
