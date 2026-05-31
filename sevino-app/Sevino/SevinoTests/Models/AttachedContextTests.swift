import XCTest
@testable import Sevino

/// Tests for the `AttachedContext` wire shape and the persisted-block resume
/// mapper (SEV-615). `wireContext` nests per-kind fields under `data` beside a
/// `kind` discriminator; `fromPersisted` rebuilds the value from a persisted
/// `ContextBlock` so the chip survives a conversation resume.
final class AttachedContextTests: XCTestCase {

    // MARK: - wireContext shape

    func testWireContextNestsDataUnderKindDiscriminator() {
        let context: AttachedContext = .funding(
            balance: 1000,
            apy: Decimal(string: "0.04")!,
            buyingPower: 2000
        )
        let wire = context.wireContext

        XCTAssertEqual(wire["kind"], .string("funding"))
        // No legacy top-level `type` key — that shape was replaced by kind+data.
        XCTAssertNil(wire["type"])
        guard case .object(let data)? = wire["data"] else {
            return XCTFail("expected `data` to be a JSON object")
        }
        XCTAssertEqual(data["balance"], .string("1000"))
        XCTAssertEqual(data["apy"], .string("0.04"))
        XCTAssertEqual(data["buying_power"], .string("2000"))
    }

    func testWireContextKindMatchesCase() {
        XCTAssertEqual(
            AttachedContext.portfolio(equity: 1, currency: "USD", gainAbs: 0, gainPct: 0, timeRange: "1D").kind,
            .portfolio
        )
        XCTAssertEqual(AttachedContext.holdings(holdings: []).kind, .holdings)
        XCTAssertEqual(AttachedContext.funding(balance: 0, apy: 0, buyingPower: 0).kind, .funding)
        XCTAssertEqual(AttachedContext.radar(items: []).kind, .radar)
    }

    // MARK: - Send → persist → resume round-trip

    func testWireContextRoundTripsThroughResumeDecode() throws {
        // The strongest symmetry check: encode `wireContext` the way send
        // does, decode it the way resume does (the response decoder
        // camelCases JSONValue keys), then rebuild — the value must survive.
        let cases: [AttachedContext] = [
            .portfolio(
                equity: Decimal(string: "12500.50")!,
                currency: "USD",
                gainAbs: Decimal(string: "350.25")!,
                gainPct: Decimal(string: "0.0288")!,
                timeRange: "1M"
            ),
            .funding(balance: 1000, apy: Decimal(string: "0.04")!, buyingPower: 2000),
            .holdings(holdings: [
                HoldingSummary(ticker: "AAPL", marketValue: 5400, unrealizedPl: 320),
                HoldingSummary(ticker: "MSFT", marketValue: 3200, unrealizedPl: nil),
            ]),
            .radar(items: [
                RadarSummary(ticker: "NVDA", description: "NVIDIA", price: "880.00", changePercent: "+2.1%", isPositive: true),
            ]),
        ]

        for original in cases {
            let wire = original.wireContext
            let persisted = JSONValue.object([
                "type": .string("context"),
                "block_id": .string("c1"),
                "kind": wire["kind"]!,
                "data": wire["data"]!,
            ])
            let bytes = try JSONEncoder.sevino().encode(persisted)
            let decoded = try JSONDecoder.sevino().decode(JSONValue.self, from: bytes)

            let restored = AttachedContext.fromPersisted(decoded, encoder: JSONEncoder.sevino())
            XCTAssertEqual(restored, original)
        }
    }

    func testFromPersistedReturnsNilForUnknownKind() throws {
        let block = JSONValue.object([
            "type": .string("context"),
            "block_id": .string("c1"),
            "kind": .string("future_kind"),
            "data": .object([:]),
        ])
        XCTAssertNil(AttachedContext.fromPersisted(block, encoder: JSONEncoder.sevino()))
    }

    func testFromPersistedReturnsNilForMalformedData() throws {
        // Valid kind, incomplete data (missing required portfolio fields).
        let block = JSONValue.object([
            "type": .string("context"),
            "block_id": .string("c1"),
            "kind": .string("portfolio"),
            "data": .object(["equity": .string("100")]),
        ])
        XCTAssertNil(AttachedContext.fromPersisted(block, encoder: JSONEncoder.sevino()))
    }
}
