import XCTest
@testable import Sevino

/**
 Round-trip tests for `Block` and `Message` (SEV-505 / C3.3).

 The reference JSON shapes mirror the backend round-trip tests in
 `sevino-api/tests/ai/unit/test_blocks.py`. If those payloads change, this
 file must change in lockstep — the wire format is the contract between
 the two ends and there is no codegen.
 */
final class BlockDecodingTests: XCTestCase {

    // MARK: - Reference payloads

    private static let textBlockJSON = """
    {"type":"text","block_id":"blk_1","text":"hello world"}
    """

    private static let statusBlockJSON = """
    {"type":"status","block_id":"blk_2","label":"Searching the web","state":"active"}
    """

    private static let stockCardBlockJSON = """
    {
      "type": "stock_card",
      "block_id": "blk_card",
      "symbol": "AMD",
      "company_name": "Advanced Micro Devices Inc.",
      "logo_url": "https://example.com/logos/amd.png",
      "price": 184.92,
      "change_abs": 2.12,
      "change_pct": 0.0116,
      "color_state": "positive",
      "bars": [
        {"t": "2026-04-29T13:30:00Z", "c": 182.80},
        {"t": "2026-04-29T13:31:00Z", "c": 183.50},
        {"t": "2026-04-29T13:32:00Z", "c": 184.92}
      ],
      "range": "1D",
      "range_options": ["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"]
    }
    """

    // MARK: - Per-variant round trip

    func testTextBlockRoundTripPreservesVariant() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.textBlockJSON.utf8)
        )

        guard case .text(let textBlock) = decoded else {
            return XCTFail("expected .text variant, got \(decoded)")
        }
        XCTAssertEqual(textBlock.blockId, "blk_1")
        XCTAssertEqual(textBlock.text, "hello world")

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testStatusBlockRoundTripPreservesVariant() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.statusBlockJSON.utf8)
        )

        guard case .status(let statusBlock) = decoded else {
            return XCTFail("expected .status variant, got \(decoded)")
        }
        XCTAssertEqual(statusBlock.blockId, "blk_2")
        XCTAssertEqual(statusBlock.label, "Searching the web")
        XCTAssertEqual(statusBlock.state, .active)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testStockCardBlockRoundTripPreservesVariant() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.stockCardBlockJSON.utf8)
        )

        guard case .stockCard(let card) = decoded else {
            return XCTFail("expected .stockCard variant, got \(decoded)")
        }
        XCTAssertEqual(card.blockId, "blk_card")
        XCTAssertEqual(card.symbol, "AMD")
        XCTAssertEqual(card.companyName, "Advanced Micro Devices Inc.")
        XCTAssertEqual(card.logoUrl, "https://example.com/logos/amd.png")
        XCTAssertEqual(card.price, 184.92, accuracy: 1e-6)
        XCTAssertEqual(card.changeAbs, 2.12, accuracy: 1e-6)
        XCTAssertEqual(card.changePct, 0.0116, accuracy: 1e-6)
        XCTAssertEqual(card.colorState, .positive)
        XCTAssertEqual(card.bars.count, 3)
        XCTAssertEqual(card.bars[0].t, "2026-04-29T13:30:00Z")
        XCTAssertEqual(card.bars[2].c, 184.92, accuracy: 1e-6)
        XCTAssertEqual(card.range, "1D")
        XCTAssertEqual(card.rangeOptions, ["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"])

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    // MARK: - Discriminator handling

    func testEncodeAlwaysIncludesTypeDiscriminator() throws {
        // Protects against future regressions where the encoder might drop
        // the discriminator — the iOS decoder dispatches on `type`, so a
        // missing field would silently break round-trips and any consumer
        // that re-decodes a previously-encoded block.
        let block = Block.text(TextBlock(blockId: "blk_1", text: "hi"))
        let json = try JSONEncoder.sevino().encode(block)
        let dict = try JSONSerialization.jsonObject(with: json) as? [String: Any]
        XCTAssertEqual(dict?["type"] as? String, "text")
    }

    func testStockCardTypeEncodesAsSnakeCaseString() throws {
        // The discriminator value `stock_card` is a literal — `convertToSnakeCase`
        // only transforms keys, so the case label `stockCard` must be written
        // as `"stock_card"` in JSON. Pin that explicitly.
        let block = makeStockCardBlock()
        let json = try JSONEncoder.sevino().encode(block)
        let dict = try JSONSerialization.jsonObject(with: json) as? [String: Any]
        XCTAssertEqual(dict?["type"] as? String, "stock_card")
    }

    func testUnknownTypeIsRejected() {
        let json = Data("""
        {"type":"image","block_id":"x","url":"https://example.com"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testTextBlockWithoutBlockIdDecodesWithSyntheticId() throws {
        // Backwards compat for legacy user messages persisted before the
        // loop minted a `block_id` for user blocks — the wire payload
        // omits the field. Decoder must mint a fresh id rather than
        // rejecting the block, otherwise the iOS resume path drops the
        // user bubble and the conversation renders without user turns.
        let json = Data(#"{"type":"text","text":"how is AMD"}"#.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .text(let block) = decoded else {
            return XCTFail("expected .text variant, got \(decoded)")
        }
        XCTAssertEqual(block.text, "how is AMD")
        XCTAssertFalse(block.blockId.isEmpty, "blockId fallback must be non-empty")
    }

    func testMissingDiscriminatorIsRejected() {
        let json = Data("""
        {"block_id":"x","text":"hi"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testInvalidStatusStateIsRejected() {
        // The state literal is a closed set on the wire — pin it so a future
        // "fall back to .active" hack on the decoder can't slip through.
        let json = Data("""
        {"type":"status","block_id":"x","label":"x","state":"pending"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testInvalidColorStateIsRejected() {
        let json = Data("""
        {"type":"stock_card","block_id":"x","symbol":"X","company_name":"X",
         "price":1,"change_abs":0,"change_pct":0,"color_state":"blue",
         "bars":[],"range":"1D","range_options":["1D"]}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    // MARK: - Optional fields

    func testStockCardDecodesWithoutLogoUrl() throws {
        // `logoUrl` is the only optional field; the backend defaults it to
        // None when the tool can't resolve a logo. Decoding must accept the
        // omitted key as nil rather than rejecting the payload.
        let json = Data("""
        {"type":"stock_card","block_id":"x","symbol":"X","company_name":"X",
         "price":1,"change_abs":0,"change_pct":0,"color_state":"neutral",
         "bars":[],"range":"1D","range_options":["1D"]}
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .stockCard(let card) = decoded else {
            return XCTFail("expected .stockCard variant, got \(decoded)")
        }
        XCTAssertNil(card.logoUrl)
    }

    // MARK: - List round trip

    func testListRoundTripPreservesOrderAndVariants() throws {
        let json = Data("""
        [
          \(Self.statusBlockJSON),
          \(Self.textBlockJSON),
          \(Self.stockCardBlockJSON)
        ]
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode([Block].self, from: json)
        XCTAssertEqual(decoded.count, 3)

        guard case .status = decoded[0] else { return XCTFail("blocks[0] not .status") }
        guard case .text = decoded[1] else { return XCTFail("blocks[1] not .text") }
        guard case .stockCard = decoded[2] else { return XCTFail("blocks[2] not .stockCard") }

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode([Block].self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    // MARK: - Identifiable / patch protocol

    func testIdentifiableExposesBlockId() {
        let block = Block.text(TextBlock(blockId: "blk_42", text: ""))
        XCTAssertEqual(block.id, "blk_42")
        XCTAssertEqual(block.blockId, "blk_42")
    }

    func testBlockIdMutationPatchesBlockInPlace() throws {
        // The acceptance criterion for SEV-505: a `block_data` patch identifies
        // the target block by `block_id` and the store rebuilds the block in
        // place within `var blocks: [Block]` without disturbing siblings.
        var message = Message(
            id: UUID(),
            role: .assistant,
            blocks: [
                .status(StatusBlock(blockId: "s1", label: "Searching", state: .active)),
                .text(TextBlock(blockId: "t1", text: "old text")),
                makeStockCardBlock(),
            ]
        )

        let targetIndex = try XCTUnwrap(
            message.blocks.firstIndex { $0.blockId == "t1" },
            "expected block t1 in message"
        )
        message.blocks[targetIndex] = .text(TextBlock(blockId: "t1", text: "new text"))

        XCTAssertEqual(message.blocks.count, 3)
        guard case .status(let still) = message.blocks[0], still.label == "Searching" else {
            return XCTFail("status block should be untouched")
        }
        guard case .text(let updated) = message.blocks[1] else {
            return XCTFail("text block should still be at index 1")
        }
        XCTAssertEqual(updated.blockId, "t1")
        XCTAssertEqual(updated.text, "new text")
        guard case .stockCard = message.blocks[2] else {
            return XCTFail("stock card block should be untouched")
        }
    }

    // MARK: - Helpers

    private func makeStockCardBlock() -> Block {
        .stockCard(
            StockCardBlock(
                blockId: "blk_card",
                symbol: "AMD",
                companyName: "Advanced Micro Devices Inc.",
                logoUrl: "https://example.com/logos/amd.png",
                price: 184.92,
                changeAbs: 2.12,
                changePct: 0.0116,
                colorState: .positive,
                bars: [
                    Bar(t: "2026-04-29T13:30:00Z", c: 182.80),
                    Bar(t: "2026-04-29T13:31:00Z", c: 183.50),
                    Bar(t: "2026-04-29T13:32:00Z", c: 184.92),
                ],
                range: "1D",
                rangeOptions: ["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"]
            )
        )
    }
}
