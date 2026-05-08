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

    /// Per-block stable identifier used for `Identifiable` and as the target
    /// of `block_data` patches. Mirrors the backend's `block_id` field.
    var blockId: String {
        switch self {
        case .text(let block): return block.blockId
        case .status(let block): return block.blockId
        case .stockCard(let block): return block.blockId
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
        }
    }
}

/// Plain markdown payload — rendered with `swift-markdown-ui` per C4.1.
/// Streamed via `text_delta` events that append to `text` between
/// `block_start` and `block_end`.
struct TextBlock: Codable, Equatable, Sendable {
    let blockId: String
    let text: String
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

/// Inline stock card with header, price/change row, sparkline, and range
/// pills. Rendered by `StockCardView` (C4.3). `bars` and `price` arrive
/// incrementally via `block_data` patches as the tool fetches data.
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
    let range: String
    let rangeOptions: [String]
}

enum ColorState: String, Codable, Sendable {
    case positive
    case negative
    case neutral
}
