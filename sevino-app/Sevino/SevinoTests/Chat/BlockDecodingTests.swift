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

    private static let thinkingStreamingJSON = """
    {"type":"thinking","block_id":"blk_th","text":"Let me think.","redacted":false,"state":"streaming"}
    """

    private static let thinkingCompleteJSON = """
    {"type":"thinking","block_id":"blk_th_complete","text":"The answer is straightforward.","redacted":false,"state":"complete"}
    """

    private static let thinkingRedactedJSON = """
    {"type":"thinking","block_id":"blk_th_redacted","text":"","redacted":true,"state":"complete"}
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

    func testThinkingStreamingBlockRoundTrip() throws {
        // SEV-571: streaming thinking block decodes with state=.streaming
        // and round-trips byte-for-byte.
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.thinkingStreamingJSON.utf8)
        )

        guard case .thinking(let thinkingBlock) = decoded else {
            return XCTFail("expected .thinking variant, got \(decoded)")
        }
        XCTAssertEqual(thinkingBlock.blockId, "blk_th")
        XCTAssertEqual(thinkingBlock.text, "Let me think.")
        XCTAssertFalse(thinkingBlock.redacted)
        XCTAssertEqual(thinkingBlock.state, .streaming)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testThinkingCompleteBlockRoundTrip() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.thinkingCompleteJSON.utf8)
        )

        guard case .thinking(let thinkingBlock) = decoded else {
            return XCTFail("expected .thinking variant, got \(decoded)")
        }
        XCTAssertEqual(thinkingBlock.state, .complete)
        XCTAssertEqual(thinkingBlock.text, "The answer is straightforward.")

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testThinkingRedactedBlockRoundTrip() throws {
        // SEV-571: redacted_thinking carries encrypted content we can't
        // show. Decodes with redacted=true and empty text; should
        // round-trip unchanged.
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.thinkingRedactedJSON.utf8)
        )

        guard case .thinking(let thinkingBlock) = decoded else {
            return XCTFail("expected .thinking variant, got \(decoded)")
        }
        XCTAssertTrue(thinkingBlock.redacted)
        XCTAssertEqual(thinkingBlock.text, "")
        XCTAssertEqual(thinkingBlock.state, .complete)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testThinkingBlockMinimalPayloadDecodesWithDefaults() throws {
        // SEV-571: an initial `block_start` may carry only `block_id`
        // (defaults: text="", redacted=false, state=.streaming). Without
        // these decoder fallbacks the streaming-start frame would throw
        // and iOS would drop the entire thinking envelope.
        let json = Data(#"{"type":"thinking","block_id":"blk_th_min"}"#.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .thinking(let block) = decoded else {
            return XCTFail("expected .thinking variant, got \(decoded)")
        }
        XCTAssertEqual(block.blockId, "blk_th_min")
        XCTAssertEqual(block.text, "")
        XCTAssertFalse(block.redacted)
        XCTAssertEqual(block.state, .streaming)
    }

    func testInvalidThinkingStateIsRejected() {
        let json = Data("""
        {"type":"thinking","block_id":"x","state":"paused"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testNullThinkingStateIsRejected() {
        // The decoder's "missing-key falls back, present-but-invalid
        // throws" stance is asserted by this case: `null` is *present*
        // but doesn't decode to a `ThinkingState`, so it must throw
        // rather than silently fall back to `.streaming`. Locks the
        // decoder pattern (`contains(.state) ? try decode : default`)
        // against a future drift to `decodeIfPresent ?? default`,
        // which would silently swallow the malformed value.
        let json = Data("""
        {"type":"thinking","block_id":"x","state":null}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
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

    func testStockCardDecodesWithoutOptionalFields() throws {
        // `logoUrl`, `barsByRange`, and `stats` are all optional. The
        // single-range / compact path omits them; decoding must accept
        // the missing keys as nil rather than rejecting the payload.
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
        XCTAssertNil(card.barsByRange)
        XCTAssertNil(card.stats)
    }

    // MARK: - Multi-range bars

    func testStockCardBarsByRangeRoundTrips() throws {
        // Encoded as a list of {range, bars} (not a dict) so literal range
        // labels like "1D" aren't subject to `convertToSnakeCase` mangling.
        // Verify the list survives a round trip with labels preserved and
        // bars typed as Bar instances.
        let json = Data("""
        {
          "type": "stock_card",
          "block_id": "x",
          "symbol": "AMD",
          "company_name": "AMD",
          "price": 184.92,
          "change_abs": 2.12,
          "change_pct": 0.0116,
          "color_state": "positive",
          "bars": [{"t": "2026-04-29T13:00:00Z", "c": 184.92}],
          "bars_by_range": [
            {
              "range": "1D",
              "bars": [{"t": "2026-04-29T13:00:00Z", "c": 184.92}],
              "change_abs": 2.12,
              "change_pct": 0.0116
            },
            {
              "range": "1Y",
              "bars": [
                {"t": "2025-04-29T13:00:00Z", "c": 100.10},
                {"t": "2026-04-29T13:00:00Z", "c": 184.92}
              ],
              "change_abs": 84.82,
              "change_pct": 0.8474
            }
          ],
          "range": "1D",
          "range_options": ["1D", "1Y"]
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .stockCard(let card) = decoded else {
            return XCTFail("expected .stockCard variant, got \(decoded)")
        }

        let byRange = try XCTUnwrap(card.barsByRange)
        XCTAssertEqual(byRange.map(\.range), ["1D", "1Y"])
        XCTAssertEqual(byRange[1].bars.count, 2)

        // The bars(for:) resolver returns per-range bars when present.
        XCTAssertEqual(card.bars(for: "1Y").count, 2)
        // Unknown ranges fall back to `bars`.
        XCTAssertEqual(card.bars(for: "5Y").count, 1)

        // change(for:) returns the per-range change values when present.
        XCTAssertEqual(card.change(for: "1D").abs, 2.12, accuracy: 1e-6)
        XCTAssertEqual(card.change(for: "1Y").abs, 84.82, accuracy: 1e-6)
        XCTAssertEqual(card.change(for: "1Y").pct, 0.8474, accuracy: 1e-6)
        // Unknown range falls back to top-level changeAbs/changePct.
        XCTAssertEqual(card.change(for: "UNKNOWN").abs, card.changeAbs)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testBarsForRangeFallsBackToBarsWhenByRangeNil() {
        // No `bars_by_range` field → every requested range returns the
        // initial `bars` array. The slider visually slides but data
        // doesn't actually change.
        let card = StockCardBlock(
            blockId: "x",
            symbol: "X",
            companyName: "X",
            price: 1,
            changeAbs: 0,
            changePct: 0,
            colorState: .neutral,
            bars: [Bar(t: "2026-04-29T13:00:00Z", c: 1.0)],
            range: "1M",
            rangeOptions: ["1D", "1M"]
        )

        XCTAssertEqual(card.bars(for: "1D").count, 1)
        XCTAssertEqual(card.bars(for: "1M").count, 1)
    }

    // MARK: - Stats grid

    func testStockCardStatsRoundTrips() throws {
        // Expanded card carries a full stats grid with money values as
        // decimal strings and counts as ints.
        let json = Data("""
        {
          "type": "stock_card",
          "block_id": "x",
          "symbol": "AMD",
          "company_name": "AMD",
          "price": 184.92,
          "change_abs": 2.12,
          "change_pct": 0.0116,
          "color_state": "positive",
          "bars": [],
          "range": "1M",
          "range_options": ["1M"],
          "stats": {
            "open": "188.00",
            "day_high": "190.00",
            "day_low": "187.50",
            "previous_close": "183.69",
            "year_high": "199.62",
            "year_low": "164.08",
            "volume": 50000000,
            "avg_volume": 60000000,
            "market_cap": 3500000000000,
            "pe_ratio": "23.45",
            "eps": "8.10",
            "beta": "1.25",
            "dividend_yield": "0.0048",
            "exchange": "NASDAQ"
          }
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .stockCard(let card) = decoded else {
            return XCTFail("expected .stockCard variant, got \(decoded)")
        }

        let stats = try XCTUnwrap(card.stats)
        XCTAssertEqual(stats.open, "188.00")
        XCTAssertEqual(stats.marketCap, 3_500_000_000_000)
        XCTAssertEqual(stats.peRatio, "23.45")
        XCTAssertEqual(stats.dividendYield, "0.0048")
        XCTAssertEqual(stats.exchange, "NASDAQ")

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testStockCardStatsWithPartialFieldsDecodes() throws {
        // FMP doesn't always return every value (beta/EPS often null);
        // partial stats must validate so the iOS card omits rows for
        // nil fields rather than failing the whole decode.
        let json = Data("""
        {
          "type": "stock_card",
          "block_id": "x",
          "symbol": "AMD",
          "company_name": "AMD",
          "price": 1,
          "change_abs": 0,
          "change_pct": 0,
          "color_state": "neutral",
          "bars": [],
          "range": "1M",
          "range_options": ["1M"],
          "stats": {"market_cap": 1000000000, "exchange": "NASDAQ"}
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .stockCard(let card) = decoded else {
            return XCTFail("expected .stockCard variant, got \(decoded)")
        }

        let stats = try XCTUnwrap(card.stats)
        XCTAssertEqual(stats.marketCap, 1_000_000_000)
        XCTAssertEqual(stats.exchange, "NASDAQ")
        XCTAssertNil(stats.beta)
        XCTAssertNil(stats.eps)
        XCTAssertNil(stats.peRatio)
    }

    // MARK: - Cancel order block

    private static let cancelOrderLimitBuyPartialJSON = """
    {
      "type": "cancel_order",
      "block_id": "blk_co",
      "order_id": "ord_co",
      "symbol": "AAPL",
      "company_name": "Apple Inc.",
      "side": "buy",
      "order_type": "limit",
      "qty": "10",
      "notional": null,
      "limit_price": "190.00",
      "filled_qty": "3",
      "time_in_force": "day",
      "submitted_at": "2026-05-31T17:04:00Z",
      "status": "pending"
    }
    """

    func testCancelOrderLimitBuyPartialFillRoundTrips() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.cancelOrderLimitBuyPartialJSON.utf8)
        )

        guard case .cancelOrder(let block) = decoded else {
            return XCTFail("expected .cancelOrder variant, got \(decoded)")
        }
        XCTAssertEqual(block.blockId, "blk_co")
        XCTAssertEqual(block.orderId, "ord_co")
        XCTAssertEqual(block.symbol, "AAPL")
        XCTAssertEqual(block.companyName, "Apple Inc.")
        XCTAssertEqual(block.side, .buy)
        XCTAssertEqual(block.orderType, .limit)
        XCTAssertEqual(block.qty, Decimal(10))
        XCTAssertNil(block.notional)
        XCTAssertEqual(block.limitPrice, Decimal(string: "190.00"))
        XCTAssertEqual(block.filledQty, Decimal(3))
        XCTAssertEqual(block.timeInForce, "day")
        XCTAssertEqual(block.status, .pending)
        XCTAssertEqual(block.id, "blk_co")

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testCancelOrderMarketSellByNotionalCancelledRoundTrips() throws {
        let json = Data("""
        {
          "type": "cancel_order",
          "block_id": "blk_x",
          "order_id": "ord_x",
          "symbol": "TSLA",
          "company_name": "Tesla, Inc.",
          "side": "sell",
          "order_type": "market",
          "notional": "500.00",
          "filled_qty": "0",
          "time_in_force": "gtc",
          "submitted_at": "2026-05-31T17:04:00Z",
          "status": "cancelled"
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .cancelOrder(let block) = decoded else {
            return XCTFail("expected .cancelOrder variant, got \(decoded)")
        }
        XCTAssertEqual(block.side, .sell)
        XCTAssertEqual(block.orderType, .market)
        XCTAssertNil(block.qty)
        XCTAssertEqual(block.notional, Decimal(string: "500.00"))
        XCTAssertNil(block.limitPrice)
        XCTAssertEqual(block.filledQty, Decimal(0))
        XCTAssertEqual(block.status, .cancelled)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testCancelOrderMarketBuyByQtyFailedRoundTrips() throws {
        let json = Data("""
        {
          "type": "cancel_order",
          "block_id": "blk_f",
          "order_id": "ord_f",
          "symbol": "AAPL",
          "company_name": "Apple Inc.",
          "side": "buy",
          "order_type": "market",
          "qty": "10",
          "filled_qty": "0",
          "time_in_force": "day",
          "submitted_at": "2026-05-31T17:04:00Z",
          "status": "failed"
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .cancelOrder(let block) = decoded else {
            return XCTFail("expected .cancelOrder variant, got \(decoded)")
        }
        XCTAssertEqual(block.orderType, .market)
        XCTAssertEqual(block.qty, Decimal(10))
        XCTAssertNil(block.notional)
        XCTAssertEqual(block.status, .failed)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testCancelOrderDecodesWithoutOptionalCompanyName() throws {
        // `company_name`, `qty`, `notional`, and `limit_price` are all
        // optional. A notional market order omits qty/limit; company_name may
        // be absent. Missing keys must decode as nil, not reject the payload.
        let json = Data("""
        {
          "type": "cancel_order",
          "block_id": "blk_min",
          "order_id": "ord_min",
          "symbol": "AAPL",
          "side": "buy",
          "order_type": "market",
          "notional": "250.00",
          "filled_qty": "0",
          "time_in_force": "day",
          "submitted_at": "2026-05-31T17:04:00Z",
          "status": "pending"
        }
        """.utf8)

        let decoded = try JSONDecoder.sevino().decode(Block.self, from: json)
        guard case .cancelOrder(let block) = decoded else {
            return XCTFail("expected .cancelOrder variant, got \(decoded)")
        }
        XCTAssertNil(block.companyName)
        XCTAssertNil(block.qty)
        XCTAssertNil(block.limitPrice)
        XCTAssertEqual(block.notional, Decimal(string: "250.00"))
    }

    func testCancelOrderUnknownStatusFailsClosed() {
        let json = Data("""
        {"type":"cancel_order","block_id":"x","order_id":"o","symbol":"X","side":"buy",
         "order_type":"market","qty":"1","filled_qty":"0","time_in_force":"day",
         "submitted_at":"2026-05-31T17:04:00Z","status":"bogus"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testCancelOrderUnknownOrderTypeFailsClosed() {
        let json = Data("""
        {"type":"cancel_order","block_id":"x","order_id":"o","symbol":"X","side":"buy",
         "order_type":"stop","qty":"1","filled_qty":"0","time_in_force":"day",
         "submitted_at":"2026-05-31T17:04:00Z","status":"pending"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testCancelOrderUnknownSideFailsClosed() {
        let json = Data("""
        {"type":"cancel_order","block_id":"x","order_id":"o","symbol":"X","side":"hold",
         "order_type":"market","qty":"1","filled_qty":"0","time_in_force":"day",
         "submitted_at":"2026-05-31T17:04:00Z","status":"pending"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testCancelOrderInvalidDecimalStringFailsClosed() {
        // Money / qty fields are decimal strings, never bare numbers. A
        // non-numeric string must reject the payload rather than coerce.
        let json = Data("""
        {"type":"cancel_order","block_id":"x","order_id":"o","symbol":"X","side":"buy",
         "order_type":"market","qty":"ten","filled_qty":"0","time_in_force":"day",
         "submitted_at":"2026-05-31T17:04:00Z","status":"pending"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    // MARK: - Stock comparison (SEV-658)

    private static let comparisonStocksJSON = """
    {
      "type": "stock_comparison",
      "block_id": "cmp_stocks",
      "assets": [
        {
          "symbol": "AAPL",
          "name": "Apple Inc.",
          "asset_type": "stock",
          "color_hex": "#5E5CE6",
          "current_price": "229.87",
          "change_pct": "0.0124",
          "series": [
            {"timestamp": "2026-04-27T13:30:00Z", "price": "221.00"},
            {"timestamp": "2026-04-28T13:30:00Z", "price": "225.40"},
            {"timestamp": "2026-04-29T13:30:00Z", "price": "229.87"}
          ],
          "metrics": {
            "pe_ratio": "34.2",
            "market_cap": "3480000000000",
            "revenue_growth_pct": "0.061",
            "earnings_growth_pct": "0.078",
            "beta": "1.21",
            "sector": "Technology",
            "one_line_distinction": "Services margin keeps expanding."
          }
        },
        {
          "symbol": "MSFT",
          "name": "Microsoft Corp.",
          "asset_type": "stock",
          "color_hex": "#30D158",
          "current_price": "430.16",
          "change_pct": "-0.0042",
          "series": [
            {"timestamp": "2026-04-28T13:30:00Z", "price": "431.00"},
            {"timestamp": "2026-04-29T13:30:00Z", "price": "430.16"}
          ],
          "metrics": {
            "pe_ratio": "36.8",
            "market_cap": "3200000000000",
            "revenue_growth_pct": "0.155",
            "earnings_growth_pct": "0.102",
            "beta": "0.92",
            "sector": "Technology",
            "one_line_distinction": "Azure remains the growth engine."
          }
        }
      ],
      "range": "1M",
      "available_ranges": ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"]
    }
    """

    private static let comparisonETFsJSON = """
    {
      "type": "stock_comparison",
      "block_id": "cmp_etfs",
      "assets": [
        {
          "symbol": "VOO",
          "name": "Vanguard S&P 500 ETF",
          "asset_type": "etf",
          "color_hex": "#0A84FF",
          "current_price": "512.34",
          "change_pct": "0.0031",
          "series": [
            {"timestamp": "2026-04-28T13:30:00Z", "price": "511.00"},
            {"timestamp": "2026-04-29T13:30:00Z", "price": "512.34"}
          ],
          "metrics": {
            "expense_ratio_pct": "0.0003",
            "aum": "1300000000000",
            "dividend_yield_pct": "0.0131",
            "holdings_count": 503,
            "index_tracked": "S&P 500",
            "top_sectors": [
              {"name": "Tech", "weight_pct": "0.31"},
              {"name": "Financials", "weight_pct": "0.13"}
            ],
            "one_line_distinction": "Pure large-cap S&P 500 exposure."
          }
        },
        {
          "symbol": "VTI",
          "name": "Vanguard Total Stock Market ETF",
          "asset_type": "etf",
          "color_hex": "#FF9F0A",
          "current_price": "287.91",
          "change_pct": "0.0028",
          "series": [
            {"timestamp": "2026-04-28T13:30:00Z", "price": "287.00"},
            {"timestamp": "2026-04-29T13:30:00Z", "price": "287.91"}
          ],
          "metrics": {
            "expense_ratio_pct": "0.0003",
            "aum": "450000000000",
            "dividend_yield_pct": "0.0128",
            "holdings_count": 3700,
            "index_tracked": "CRSP US Total Market",
            "top_sectors": [
              {"name": "Tech", "weight_pct": "0.29"},
              {"name": "Financials", "weight_pct": "0.13"}
            ]
          }
        }
      ],
      "range": "3M",
      "available_ranges": ["1M", "3M", "YTD", "1Y", "5Y"],
      "holdings_overlap_pct": "0.84"
    }
    """

    private static let comparisonAsymmetricJSON = """
    {
      "type": "stock_comparison",
      "block_id": "cmp_mixed",
      "assets": [
        {
          "symbol": "NVDA",
          "name": "NVIDIA Corp.",
          "asset_type": "stock",
          "color_hex": "#5E5CE6",
          "current_price": "138.07",
          "change_pct": "0.0212",
          "series": [
            {"timestamp": "2026-04-28T13:30:00Z", "price": "137.00"},
            {"timestamp": "2026-04-29T13:30:00Z", "price": "138.07"}
          ],
          "metrics": {
            "pe_ratio": "64.5",
            "revenue_growth_pct": "0.94",
            "beta": "1.68",
            "sector": "Technology",
            "one_line_distinction": "Highest beta, highest growth."
          }
        },
        {
          "symbol": "SMH",
          "name": "VanEck Semiconductor ETF",
          "asset_type": "etf",
          "color_hex": "#FF9F0A",
          "current_price": "248.55",
          "change_pct": "0.0156",
          "series": [
            {"timestamp": "2026-04-28T13:30:00Z", "price": "247.00"},
            {"timestamp": "2026-04-29T13:30:00Z", "price": "248.55"}
          ],
          "metrics": {
            "expense_ratio_pct": "0.0035",
            "holdings_count": 25,
            "dividend_yield_pct": "0.006",
            "index_tracked": "MVIS US Listed Semiconductor 25",
            "top_sectors": [
              {"name": "Semis", "weight_pct": "0.78"},
              {"name": "Equipment", "weight_pct": "0.18"}
            ]
          }
        }
      ],
      "range": "1M",
      "available_ranges": ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"],
      "narration": "NVDA is a single stock; SMH is a semiconductor ETF holding NVDA plus 24 peers."
    }
    """

    private static let comparisonThreeStocksJSON = """
    {
      "type": "stock_comparison",
      "block_id": "cmp_three",
      "assets": [
        {
          "symbol": "NVDA",
          "name": "NVIDIA Corp.",
          "asset_type": "stock",
          "color_hex": "#5E5CE6",
          "current_price": "138.07",
          "change_pct": "0.0212",
          "series": [{"timestamp": "2026-04-29T13:30:00Z", "price": "138.07"}],
          "metrics": {"pe_ratio": "64.5", "beta": "1.68", "sector": "Technology"}
        },
        {
          "symbol": "AMD",
          "name": "Advanced Micro Devices",
          "asset_type": "stock",
          "color_hex": "#30D158",
          "current_price": "164.08",
          "change_pct": "0.0087",
          "series": [{"timestamp": "2026-04-29T13:30:00Z", "price": "164.08"}],
          "metrics": {"pe_ratio": "47.3", "beta": "1.74", "sector": "Technology"}
        },
        {
          "symbol": "INTC",
          "name": "Intel Corp.",
          "asset_type": "stock",
          "color_hex": "#FF453A",
          "current_price": "23.41",
          "change_pct": "-0.0153",
          "series": [{"timestamp": "2026-04-29T13:30:00Z", "price": "23.41"}],
          "metrics": {"beta": "1.05", "sector": "Technology"}
        }
      ],
      "range": "1M",
      "available_ranges": ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"]
    }
    """

    @discardableResult
    private func decodeComparison(
        _ json: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws -> StockComparisonBlock {
        let decoded = try JSONDecoder.sevino().decode(Block.self, from: Data(json.utf8))
        guard case .stockComparison(let block) = decoded else {
            XCTFail("expected .stockComparison variant, got \(decoded)", file: file, line: line)
            throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "wrong variant"))
        }
        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded, "round trip changed the block", file: file, line: line)
        return block
    }

    func testComparisonStocksRoundTrip() throws {
        let block = try decodeComparison(Self.comparisonStocksJSON)
        XCTAssertEqual(block.blockId, "cmp_stocks")
        XCTAssertEqual(block.range, "1M")
        XCTAssertEqual(block.availableRanges, ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"])
        XCTAssertNil(block.narration)
        XCTAssertNil(block.holdingsOverlapPct)
        XCTAssertEqual(block.assets.count, 2)

        let aapl = block.assets[0]
        XCTAssertEqual(aapl.symbol, "AAPL")
        XCTAssertEqual(aapl.assetType, .stock)
        XCTAssertEqual(aapl.colorHex, "#5E5CE6")
        XCTAssertEqual(aapl.currentPrice, Decimal(string: "229.87"))
        XCTAssertEqual(aapl.changePct, Decimal(string: "0.0124"))
        XCTAssertEqual(aapl.series.count, 3)
        XCTAssertEqual(aapl.series[2].price, Decimal(string: "229.87"))
        XCTAssertEqual(aapl.metrics.peRatio, Decimal(string: "34.2"))
        XCTAssertEqual(aapl.metrics.marketCap, Decimal(string: "3480000000000"))
        XCTAssertEqual(aapl.metrics.sector, "Technology")
        XCTAssertNil(aapl.metrics.expenseRatioPct)
        XCTAssertNil(aapl.metrics.topSectors)
    }

    func testComparisonETFsRoundTrip() throws {
        let block = try decodeComparison(Self.comparisonETFsJSON)
        XCTAssertEqual(block.holdingsOverlapPct, Decimal(string: "0.84"))
        XCTAssertEqual(block.assets.map(\.assetType), [.etf, .etf])

        let voo = block.assets[0]
        XCTAssertEqual(voo.metrics.expenseRatioPct, Decimal(string: "0.0003"))
        XCTAssertEqual(voo.metrics.aum, Decimal(string: "1300000000000"))
        XCTAssertEqual(voo.metrics.holdingsCount, 503)
        XCTAssertEqual(voo.metrics.indexTracked, "S&P 500")
        let sectors = try XCTUnwrap(voo.metrics.topSectors)
        XCTAssertEqual(sectors.map(\.name), ["Tech", "Financials"])
        XCTAssertEqual(sectors[0].weightPct, Decimal(string: "0.31"))
        XCTAssertNil(voo.metrics.peRatio)
    }

    func testComparisonAsymmetricRoundTrip() throws {
        let block = try decodeComparison(Self.comparisonAsymmetricJSON)
        XCTAssertEqual(block.narration, "NVDA is a single stock; SMH is a semiconductor ETF holding NVDA plus 24 peers.")
        XCTAssertEqual(block.assets.map(\.assetType), [.stock, .etf])
        XCTAssertEqual(block.assets[0].metrics.peRatio, Decimal(string: "64.5"))
        XCTAssertEqual(block.assets[1].metrics.holdingsCount, 25)
        XCTAssertNil(block.assets[0].metrics.expenseRatioPct)
        XCTAssertNil(block.assets[1].metrics.peRatio)
    }

    func testComparisonThreeStocksRoundTrip() throws {
        let block = try decodeComparison(Self.comparisonThreeStocksJSON)
        XCTAssertEqual(block.assets.count, 3)
        XCTAssertEqual(block.assets.map(\.symbol), ["NVDA", "AMD", "INTC"])
        // INTC omits pe_ratio / market_cap — those decode to nil, not a failure.
        XCTAssertNil(block.assets[2].metrics.peRatio)
        XCTAssertNil(block.assets[2].metrics.marketCap)
        XCTAssertEqual(block.assets[2].metrics.beta, Decimal(string: "1.05"))
    }

    func testComparisonUnknownAssetTypeFailsClosed() {
        // A malformed `asset_type` must reject the whole block rather than
        // defaulting to a type and mis-rendering the metric panel.
        let json = Data("""
        {
          "type": "stock_comparison",
          "block_id": "cmp_bad",
          "assets": [
            {
              "symbol": "BTC", "name": "Bitcoin", "asset_type": "crypto",
              "color_hex": "#F7931A", "current_price": "1.0", "change_pct": "0.0",
              "series": [], "metrics": {}
            }
          ],
          "range": "1M",
          "available_ranges": ["1M"]
        }
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testComparisonEmptyMetricsDecodeToNil() throws {
        let json = """
        {
          "type": "stock_comparison",
          "block_id": "cmp_minimal",
          "assets": [
            {
              "symbol": "X", "name": "X", "asset_type": "stock",
              "color_hex": "#FFFFFF", "current_price": "1.0", "change_pct": "0.0",
              "series": [], "metrics": {}
            }
          ],
          "range": "1M",
          "available_ranges": ["1M"]
        }
        """
        let block = try decodeComparison(json)
        let metrics = block.assets[0].metrics
        XCTAssertNil(metrics.peRatio)
        XCTAssertNil(metrics.marketCap)
        XCTAssertNil(metrics.revenueGrowthPct)
        XCTAssertNil(metrics.beta)
        XCTAssertNil(metrics.sector)
        XCTAssertNil(metrics.expenseRatioPct)
        XCTAssertNil(metrics.aum)
        XCTAssertNil(metrics.holdingsCount)
        XCTAssertNil(metrics.dividendYieldPct)
        XCTAssertNil(metrics.indexTracked)
        XCTAssertNil(metrics.topSectors)
        XCTAssertNil(metrics.oneLineDistinction)
    }

    func testComparisonTypeEncodesAsSnakeCaseString() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.comparisonStocksJSON.utf8)
        )
        let json = try JSONEncoder.sevino().encode(decoded)
        let dict = try JSONSerialization.jsonObject(with: json) as? [String: Any]
        XCTAssertEqual(dict?["type"] as? String, "stock_comparison")
    }

    // MARK: - CancelTransferBlock decoding

    private static let cancelTransferPendingJSON = """
    {
      "type": "cancel_transfer",
      "block_id": "blk_xfer_1",
      "transfer_id": "trf_abc123",
      "direction": "deposit",
      "amount": "500.00",
      "bank_name": "Chase",
      "bank_mask": "1234",
      "initiated_at": "2026-05-31T14:30:00Z",
      "status": "pending"
    }
    """

    private func cancelTransferJSON(
        direction: String,
        status: String,
        includeMask: Bool = true
    ) -> Data {
        let maskLine = includeMask ? "\"bank_mask\": \"5678\"," : ""
        return Data("""
        {
          "type": "cancel_transfer",
          "block_id": "blk_x",
          "transfer_id": "trf_x",
          "direction": "\(direction)",
          "amount": "200.00",
          "bank_name": "Wells Fargo",
          \(maskLine)
          "initiated_at": "2026-05-31T14:30:00Z",
          "status": "\(status)"
        }
        """.utf8)
    }

    func testCancelTransferPendingDepositRoundTrip() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: Data(Self.cancelTransferPendingJSON.utf8)
        )

        guard case .cancelTransfer(let ctb) = decoded else {
            return XCTFail("expected .cancelTransfer variant, got \(decoded)")
        }
        XCTAssertEqual(ctb.blockId, "blk_xfer_1")
        XCTAssertEqual(ctb.transferId, "trf_abc123")
        XCTAssertEqual(ctb.direction, .deposit)
        XCTAssertEqual(ctb.amount, Decimal(string: "500.00"))
        XCTAssertEqual(ctb.bankName, "Chase")
        XCTAssertEqual(ctb.bankMask, "1234")
        XCTAssertEqual(ctb.status, .pending)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testCancelTransferWithdrawalCancelledRoundTrip() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: cancelTransferJSON(direction: "withdraw", status: "cancelled")
        )

        guard case .cancelTransfer(let ctb) = decoded else {
            return XCTFail("expected .cancelTransfer variant, got \(decoded)")
        }
        XCTAssertEqual(ctb.direction, .withdraw)
        XCTAssertEqual(ctb.status, .cancelled)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testCancelTransferFailedStatusRoundTrip() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: cancelTransferJSON(direction: "deposit", status: "failed")
        )

        guard case .cancelTransfer(let ctb) = decoded else {
            return XCTFail("expected .cancelTransfer variant, got \(decoded)")
        }
        XCTAssertEqual(ctb.status, .failed)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(Block.self, from: reEncoded)
        XCTAssertEqual(reDecoded, decoded)
    }

    func testCancelTransferUnknownStatusIsRejected() {
        // The status literal is a closed set on the wire — an unrecognized
        // value must fail closed rather than silently degrade.
        XCTAssertThrowsError(
            try JSONDecoder.sevino().decode(
                Block.self,
                from: cancelTransferJSON(direction: "deposit", status: "settled")
            )
        )
    }

    func testCancelTransferUnknownDirectionIsRejected() {
        XCTAssertThrowsError(
            try JSONDecoder.sevino().decode(
                Block.self,
                from: cancelTransferJSON(direction: "swap", status: "pending")
            )
        )
    }

    func testCancelTransferMissingBankMaskDecodesToNil() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self,
            from: cancelTransferJSON(direction: "deposit", status: "pending", includeMask: false)
        )

        guard case .cancelTransfer(let ctb) = decoded else {
            return XCTFail("expected .cancelTransfer variant, got \(decoded)")
        }
        XCTAssertNil(ctb.bankMask)
    }

    func testCancelTransferNumericAmountIsRejected() {
        // Decimal-on-the-wire: amount must arrive as a string. A JSON number
        // would let a Double mediate the money value, so it must be rejected.
        let json = Data("""
        {"type":"cancel_transfer","block_id":"x","transfer_id":"t","direction":"deposit",
         "amount":500.00,"bank_name":"Chase","initiated_at":"2026-05-31T14:30:00Z","status":"pending"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
    }

    func testCancelTransferInvalidInitiatedAtIsRejected() {
        let json = Data("""
        {"type":"cancel_transfer","block_id":"x","transfer_id":"t","direction":"deposit",
         "amount":"500.00","bank_name":"Chase","initiated_at":"not-a-date","status":"pending"}
        """.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode(Block.self, from: json))
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
