import Foundation

/**
 Discriminated union of UI blocks streamed from the agent loop.

 The wire format mirrors `app/ai/blocks.py` on the backend (SEV-480 / B1.1 +
 SEV-496 / C1.3). Both ends round-trip the same JSON so a `BlockStart` event
 can carry an opaque block payload and the iOS decoder dispatches on the
 `type` discriminator. There is no codegen — adding a variant is a new case
 here plus the matching subclass on the backend, in the same PR.

 `Identifiable` returns `blockId` so SwiftUI `ForEach` can address each block
 stably across `block_data` patches. `block_id` is also the target of the
 patch protocol: `BlockData` events name the block to update, the store
 finds it by id and rebuilds the block in place.
 */
enum Block: Codable, Identifiable, Equatable, Sendable {
    case text(TextBlock)
    case status(StatusBlock)
    case stockCard(StockCardBlock)
    case stockComparison(StockComparisonBlock)
    case thinking(ThinkingBlock)

    /// Per-block stable identifier used for `Identifiable` and as the target
    /// of `block_data` patches. Mirrors the backend's `block_id` field.
    var blockId: String {
        switch self {
        case .text(let block): return block.blockId
        case .status(let block): return block.blockId
        case .stockCard(let block): return block.blockId
        case .stockComparison(let block): return block.blockId
        case .thinking(let block): return block.blockId
        }
    }

    var id: String { blockId }

    private enum DiscriminatorKey: String, CodingKey {
        case type
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: DiscriminatorKey.self)
        let type = try container.decode(String.self, forKey: .type)
        switch type {
        case "text":
            self = .text(try TextBlock(from: decoder))
        case "status":
            self = .status(try StatusBlock(from: decoder))
        case "stock_card":
            self = .stockCard(try StockCardBlock(from: decoder))
        case "stock_comparison":
            self = .stockComparison(try StockComparisonBlock(from: decoder))
        case "thinking":
            self = .thinking(try ThinkingBlock(from: decoder))
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .type,
                in: container,
                debugDescription: "Unknown block type: \(type)"
            )
        }
    }

    func encode(to encoder: any Encoder) throws {
        // The variant struct's synthesized `encode(to:)` writes its own fields
        // through a separate keyed container; both containers share the same
        // underlying JSON object on the encoder, so the merged result is one
        // flat block dict carrying the discriminator alongside the payload.
        var typeContainer = encoder.container(keyedBy: DiscriminatorKey.self)
        switch self {
        case .text(let block):
            try typeContainer.encode("text", forKey: .type)
            try block.encode(to: encoder)
        case .status(let block):
            try typeContainer.encode("status", forKey: .type)
            try block.encode(to: encoder)
        case .stockCard(let block):
            try typeContainer.encode("stock_card", forKey: .type)
            try block.encode(to: encoder)
        case .stockComparison(let block):
            try typeContainer.encode("stock_comparison", forKey: .type)
            try block.encode(to: encoder)
        case .thinking(let block):
            try typeContainer.encode("thinking", forKey: .type)
            try block.encode(to: encoder)
        }
    }
}

/// Plain markdown payload — rendered with `swift-markdown-ui` per C4.1.
/// Streamed via `text_delta` events that append to `text` between
/// `block_start` and `block_end`.
///
/// Custom `init(from:)` because the loop persists user messages as
/// ``{"type": "text", "text": "..."}`` without a `block_id` (loop.py
/// `append_user_message` call site). Resuming a conversation with the
/// synthesized decoder would reject every user block and drop user
/// bubbles entirely. We mint a fresh ULID-like id when the wire payload
/// omits it — user-message blocks never receive `block_data` patches, so
/// the synthetic id only needs to be unique within the resumed
/// transcript (not stable across reloads).
struct TextBlock: Codable, Equatable, Sendable {
    let blockId: String
    let text: String

    private enum CodingKeys: String, CodingKey {
        case blockId, text
    }

    init(blockId: String, text: String) {
        self.blockId = blockId
        self.text = text
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.text = try container.decode(String.self, forKey: .text)
        self.blockId =
            (try? container.decode(String.self, forKey: .blockId))
            ?? UUID().uuidString
    }
}

/// Inline progress pill ("Searching the web", "Fetching price"). The runtime
/// flips `state` from `active` to `complete`/`failed` in a single
/// `block_data` patch so the UI can animate the transition.
struct StatusBlock: Codable, Equatable, Sendable {
    let blockId: String
    let label: String
    let state: StatusState
}

enum StatusState: String, Codable, Sendable {
    case active
    case complete
    case failed
}

/// One price point in a `StockCardBlock` chart payload. The minimal `{t, c}`
/// shape mirrors the backend's `Bar` model — raw OHLCV stays server-side.
struct Bar: Codable, Equatable, Sendable {
    /// ISO 8601 timestamp.
    let t: String
    /// Close price.
    let c: Double
}

/// Per-range chart data + change values for one option of a
/// `StockCardBlock`. Encoded as a list (not a dict) on the wire so
/// literal range labels like "1D" aren't subject to
/// `JSONEncoder.convertToSnakeCase` mangling.
///
/// `changeAbs` / `changePct` are the BE-authoritative change values
/// for the range:
/// - For "1D", from FMP's daily quote (vs yesterday's close).
/// - For longer ranges, `current_price - first_bar.close`.
/// The iOS card reads these directly when the user slides the range
/// selector — no FE-side derivation.
struct RangeBars: Codable, Equatable, Sendable {
    let range: String
    let bars: [Bar]
    let changeAbs: Double
    let changePct: Double
}

/// Optional valuation/technical stats shown on an expanded `StockCardBlock`.
/// Every field is optional — FMP doesn't always return every value, and
/// the iOS card renders rows only for fields that arrive non-nil. Money
/// values arrive as decimal strings (decimal-on-the-wire convention);
/// the view layer formats them via `Decimal` extensions.
struct StockStats: Codable, Equatable, Sendable {
    let open: String?
    let dayHigh: String?
    let dayLow: String?
    let previousClose: String?
    let yearHigh: String?
    let yearLow: String?
    let volume: Int?
    let avgVolume: Int?
    let marketCap: Int?
    let peRatio: String?
    let eps: String?
    let beta: String?
    let dividendYield: String?
    let exchange: String?
}

/// Inline stock card with header, price/change row, sparkline, and range
/// pills. Rendered by `SingleStockCard`. `bars` and `price` arrive
/// incrementally via `block_data` patches as the tool fetches data.
///
/// When the tool pre-fetches every range up front it populates
/// `barsByRange` with one `RangeBars` entry per option. The card's
/// `bars(for:)` helper uses that list to swap chart data client-side
/// as the user slides the range selector — no refetch round trip.
/// Tools that only fetch one range omit `barsByRange`, and
/// `bars(for:)` falls back to `bars`.
///
/// `stats` is populated when the tool was called with `expanded: true`
/// and renders a grid below the chart with valuation/technical fields.
struct StockCardBlock: Codable, Equatable, Sendable {
    let blockId: String
    let symbol: String
    let companyName: String
    let logoUrl: String?
    let price: Double
    let changeAbs: Double
    let changePct: Double
    let colorState: ColorState
    let bars: [Bar]
    let barsByRange: [RangeBars]?
    let range: String
    let rangeOptions: [String]
    let stats: StockStats?

    init(
        blockId: String,
        symbol: String,
        companyName: String,
        logoUrl: String? = nil,
        price: Double,
        changeAbs: Double,
        changePct: Double,
        colorState: ColorState,
        bars: [Bar],
        barsByRange: [RangeBars]? = nil,
        range: String,
        rangeOptions: [String],
        stats: StockStats? = nil
    ) {
        self.blockId = blockId
        self.symbol = symbol
        self.companyName = companyName
        self.logoUrl = logoUrl
        self.price = price
        self.changeAbs = changeAbs
        self.changePct = changePct
        self.colorState = colorState
        self.bars = bars
        self.barsByRange = barsByRange
        self.range = range
        self.rangeOptions = rangeOptions
        self.stats = stats
    }

    /// Bars to display for `range`. Prefers `barsByRange` when the tool
    /// pre-fetched it; otherwise falls back to `bars` so the chart
    /// always renders something while the backend stays on single-range
    /// payloads.
    func bars(for range: String) -> [Bar] {
        barsByRange?.first(where: { $0.range == range })?.bars ?? bars
    }

    /// Per-range change values (`changeAbs`, `changePct`) as
    /// computed authoritatively by the tool. Falls back to the
    /// top-level daily change when `barsByRange` is missing or doesn't
    /// include `range` — same fallback semantics as `bars(for:)`.
    func change(for range: String) -> (abs: Double, pct: Double) {
        if let entry = barsByRange?.first(where: { $0.range == range }) {
            return (entry.changeAbs, entry.changePct)
        }
        return (changeAbs, changePct)
    }
}

enum ColorState: String, Codable, Sendable {
    case positive
    case negative
    case neutral
}

/// Extended-thinking output (SEV-571). Mirrors `ThinkingBlock` in
/// `app/ai/blocks.py`.
///
/// Streaming-start frames may carry only `block_id`; the explicit-
/// fallback decoder mirrors the backend's Pydantic defaults so the
/// initial `block_start` decode doesn't throw and drop the turn.
/// `redacted == true` covers Anthropic's `redacted_thinking` variant:
/// the payload is encrypted and arrives with `state == .complete` and
/// no deltas.
struct ThinkingBlock: Codable, Equatable, Sendable {
    let blockId: String
    let text: String
    let redacted: Bool
    let state: ThinkingState

    private enum CodingKeys: String, CodingKey {
        case blockId, text, redacted, state
    }

    init(
        blockId: String,
        text: String = "",
        redacted: Bool = false,
        state: ThinkingState = .streaming
    ) {
        self.blockId = blockId
        self.text = text
        self.redacted = redacted
        self.state = state
    }

    init(from decoder: any Decoder) throws {
        // "Missing falls back, present-but-invalid throws": a
        // `decodeIfPresent ?? .streaming` would silently swallow
        // malformed state literals — those are a wire-format contract
        // violation and must surface loudly. Pinned by
        // `testNullThinkingStateIsRejected`.
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.blockId = try container.decode(String.self, forKey: .blockId)
        self.text =
            container.contains(.text)
            ? try container.decode(String.self, forKey: .text)
            : ""
        self.redacted =
            container.contains(.redacted)
            ? try container.decode(Bool.self, forKey: .redacted)
            : false
        self.state =
            container.contains(.state)
            ? try container.decode(ThinkingState.self, forKey: .state)
            : .streaming
    }
}

enum ThinkingState: String, Codable, Sendable {
    case streaming
    case complete
}

/**
 Side-by-side comparison of 2–3 assets, rendered by `StockComparisonCard`
 (SEV-658).

 This wire schema is iOS-defined for now — there is no
 `display_stock_comparison` backend tool yet. When the backend ticket lands
 it must mirror this JSON exactly so the existing dispatcher routes real
 payloads to the same view with no iOS rework. Snake_case on the wire maps to
 camelCase here via the decoder's `convertFromSnakeCase` strategy.

 Wire shape:
 ```json
 {
   "type": "stock_comparison",
   "block_id": "blk_cmp",
   "assets": [ComparisonAsset, …],          // 2 or 3
   "range": "1M",                            // the range `series` covers
   "available_ranges": ["1D", "1W", "1M"],   // display-only pills
   "narration": "…" | null,                  // optional lead paragraph
   "holdings_overlap_pct": "0.85" | null     // ETF-vs-ETF only; v1 always null
 }
 ```

 Money/percent values serialize as decimal strings (`@DecimalString` /
 `@DecimalStringOptional`); percentages are factors of 1 (`0.0116` == 1.16%),
 matching the rest of the wire format.
 */
struct StockComparisonBlock: Codable, Equatable, Sendable, Identifiable {
    let blockId: String
    let assets: [ComparisonAsset]
    let range: String
    let availableRanges: [String]
    let narration: String?
    @DecimalStringOptional var holdingsOverlapPct: Decimal?

    var id: String { blockId }

    init(
        blockId: String,
        assets: [ComparisonAsset],
        range: String,
        availableRanges: [String],
        narration: String? = nil,
        holdingsOverlapPct: Decimal? = nil
    ) {
        self.blockId = blockId
        self.assets = assets
        self.range = range
        self.availableRanges = availableRanges
        self.narration = narration
        self.holdingsOverlapPct = holdingsOverlapPct
    }
}

/// One asset in a `StockComparisonBlock`. `colorHex` (e.g. `"#5E5CE6"`) is the
/// BE-assigned line/swatch color so every asset is consistent between the
/// overlay chart and the table. `metrics` is type-adaptive — stock fields are
/// populated for `.stock`, ETF fields for `.etf` (see `ComparisonAssetMetrics`).
struct ComparisonAsset: Codable, Equatable, Sendable, Identifiable {
    let symbol: String
    let name: String
    let assetType: AssetType
    let colorHex: String
    @DecimalString var currentPrice: Decimal
    @DecimalString var changePct: Decimal
    let series: [SeriesPoint]
    let metrics: ComparisonAssetMetrics

    var id: String { symbol }

    init(
        symbol: String,
        name: String,
        assetType: AssetType,
        colorHex: String,
        currentPrice: Decimal,
        changePct: Decimal,
        series: [SeriesPoint],
        metrics: ComparisonAssetMetrics
    ) {
        self.symbol = symbol
        self.name = name
        self.assetType = assetType
        self.colorHex = colorHex
        self.currentPrice = currentPrice
        self.changePct = changePct
        self.series = series
        self.metrics = metrics
    }
}

/// Unknown `asset_type` strings fail the decode closed (rather than defaulting)
/// so a malformed payload surfaces loudly instead of silently mis-rendering.
enum AssetType: String, Codable, Equatable, Sendable {
    case stock
    case etf
}

/// Type-adaptive fundamentals. Stock fields populate for `.stock`, ETF fields
/// for `.etf`; the card renders only the rows whose values arrive non-nil.
/// `oneLineDistinction` is shared and renders as an italic footnote per asset.
struct ComparisonAssetMetrics: Codable, Equatable, Sendable {
    @DecimalStringOptional var peRatio: Decimal?
    @DecimalStringOptional var marketCap: Decimal?
    @DecimalStringOptional var revenueGrowthPct: Decimal?
    @DecimalStringOptional var earningsGrowthPct: Decimal?
    @DecimalStringOptional var beta: Decimal?
    let sector: String?
    @DecimalStringOptional var expenseRatioPct: Decimal?
    @DecimalStringOptional var aum: Decimal?
    let holdingsCount: Int?
    @DecimalStringOptional var dividendYieldPct: Decimal?
    let indexTracked: String?
    let topSectors: [SectorExposure]?
    let oneLineDistinction: String?

    init(
        peRatio: Decimal? = nil,
        marketCap: Decimal? = nil,
        revenueGrowthPct: Decimal? = nil,
        earningsGrowthPct: Decimal? = nil,
        beta: Decimal? = nil,
        sector: String? = nil,
        expenseRatioPct: Decimal? = nil,
        aum: Decimal? = nil,
        holdingsCount: Int? = nil,
        dividendYieldPct: Decimal? = nil,
        indexTracked: String? = nil,
        topSectors: [SectorExposure]? = nil,
        oneLineDistinction: String? = nil
    ) {
        self.peRatio = peRatio
        self.marketCap = marketCap
        self.revenueGrowthPct = revenueGrowthPct
        self.earningsGrowthPct = earningsGrowthPct
        self.beta = beta
        self.sector = sector
        self.expenseRatioPct = expenseRatioPct
        self.aum = aum
        self.holdingsCount = holdingsCount
        self.dividendYieldPct = dividendYieldPct
        self.indexTracked = indexTracked
        self.topSectors = topSectors
        self.oneLineDistinction = oneLineDistinction
    }
}

/// One slice of an ETF's sector breakdown. `weightPct` is a factor of 1
/// (`0.30` == 30%).
struct SectorExposure: Codable, Equatable, Sendable, Identifiable {
    var id: String { name }
    let name: String
    @DecimalString var weightPct: Decimal

    init(name: String, weightPct: Decimal) {
        self.name = name
        self.weightPct = weightPct
    }
}

/// One point on an asset's overlay line.
///
/// `timestamp` codes as an ISO 8601 *string* through this type's own
/// `Codable` rather than relying on the coder's date strategy: a `block_data`
/// patch re-encodes the block through `JSONEncoder.sevino()` (which sets no
/// `dateEncodingStrategy`), so a synthesized `Date` would serialize as a bare
/// number and break the re-decode. Owning the string⇄`Date` mapping here keeps
/// the round trip stable regardless of the active coders.
struct SeriesPoint: Codable, Equatable, Sendable {
    let timestamp: Date
    @DecimalString var price: Decimal

    init(timestamp: Date, price: Decimal) {
        self.timestamp = timestamp
        self.price = price
    }

    private enum CodingKeys: String, CodingKey {
        case timestamp, price
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let raw = try container.decode(String.self, forKey: .timestamp)
        guard let date = Self.parse(raw) else {
            throw DecodingError.dataCorruptedError(
                forKey: .timestamp,
                in: container,
                debugDescription: "Invalid ISO 8601 timestamp: \(raw)"
            )
        }
        self.timestamp = date
        self._price = try container.decode(DecimalString.self, forKey: .price)
    }

    func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(Self.iso8601.string(from: timestamp), forKey: .timestamp)
        try container.encode(_price, forKey: .price)
    }

    private static func parse(_ raw: String) -> Date? {
        iso8601Fractional.date(from: raw) ?? iso8601.date(from: raw)
    }

    private static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let iso8601Fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
