import Foundation

/// Mirrors `ContextKind` in `app/schemas/conversations.py` — the wire `kind`
/// discriminator on an attached-context block. Raw values match the backend
/// enum exactly (SEV-615).
enum ContextKind: String, Codable, Sendable {
    case portfolio
    case holdings
    case funding
    case radar
}

/// Lightweight value capturing which modal was open and its snapshot data
/// so the chat can render the card inline as a user-message attachment.
enum AttachedContext: Equatable, Sendable {
    case portfolio(equity: Decimal, currency: String, gainAbs: Decimal, gainPct: Decimal, timeRange: String)
    case holdings(holdings: [HoldingSummary])
    case funding(balance: Decimal, apy: Decimal, buyingPower: Decimal)
    case radar(items: [RadarSummary])

    /// The wire `kind` discriminator for this attachment.
    var kind: ContextKind {
        switch self {
        case .portfolio: .portfolio
        case .holdings: .holdings
        case .funding: .funding
        case .radar: .radar
        }
    }

    /// Wire-format dict sent as `context` in the chat-turn request:
    /// `{ "kind": ..., "data": { ... } }`. The backend persists this verbatim
    /// as a `ContextBlock` and projects only `kind` to a short model hint;
    /// the per-kind `data` shape is opaque to the backend and read only by iOS
    /// — on send for the chip, on resume to rebuild it.
    var wireContext: [String: JSONValue] {
        ["kind": .string(kind.rawValue), "data": .object(wireData)]
    }

    /// Per-kind payload nested under `data`. Money / pct values ride as
    /// decimal strings (decimal-on-the-wire) so the resume decoder can
    /// round-trip them through `Decimal`.
    private var wireData: [String: JSONValue] {
        switch self {
        case .portfolio(let equity, let currency, let gainAbs, let gainPct, let timeRange):
            return [
                "equity": .string("\(equity)"),
                "currency": .string(currency),
                "gain_abs": .string("\(gainAbs)"),
                "gain_pct": .string("\(gainPct)"),
                "time_range": .string(timeRange),
            ]
        case .funding(let balance, let apy, let buyingPower):
            return [
                "balance": .string("\(balance)"),
                "apy": .string("\(apy)"),
                "buying_power": .string("\(buyingPower)"),
            ]
        case .holdings(let holdings):
            let list: [JSONValue] = holdings.map { h in
                var entry: [String: JSONValue] = [
                    "ticker": .string(h.ticker),
                    "market_value": .string("\(h.marketValue)"),
                ]
                if let pl = h.unrealizedPl { entry["unrealized_pl"] = .string("\(pl)") }
                return .object(entry)
            }
            return ["holdings": .array(list)]
        case .radar(let items):
            let list: [JSONValue] = items.map { item in
                .object([
                    "ticker": .string(item.ticker),
                    "description": .string(item.description),
                    "price": .string(item.price),
                    "change_percent": .string(item.changePercent),
                    "is_positive": .bool(item.isPositive),
                ])
            }
            return ["items": .array(list)]
        }
    }
}

extension AttachedContext {
    /// Rebuild from a persisted `ContextBlock` JSON object
    /// (`{ type, block_id, kind, data }`) when resuming a conversation, so the
    /// attachment chip re-renders (SEV-615).
    ///
    /// `block` is the raw JSONB value; `encoder` is the store's Sevino encoder.
    /// Re-encoding through `convertToSnakeCase` then re-parsing with a plain
    /// decoder recovers the snake_case keys the backend actually persisted —
    /// the response decoder's `convertFromSnakeCase` would otherwise have
    /// camelCased the intermediate `JSONValue`'s keys. Returns `nil` on an
    /// unknown `kind` or a malformed per-kind `data` shape; the caller drops
    /// the chip but keeps the rest of the message.
    static func fromPersisted(_ block: JSONValue, encoder: JSONEncoder) -> AttachedContext? {
        guard let bytes = try? encoder.encode(block),
              case .object(let obj)? = try? JSONDecoder().decode(JSONValue.self, from: bytes),
              case .string(let rawKind)? = obj["kind"],
              let kind = ContextKind(rawValue: rawKind),
              case .object(let data)? = obj["data"] else {
            return nil
        }

        switch kind {
        case .portfolio:
            guard let equity = data.decimalValue("equity"),
                  let currency = data.stringValue("currency"),
                  let gainAbs = data.decimalValue("gain_abs"),
                  let gainPct = data.decimalValue("gain_pct"),
                  let timeRange = data.stringValue("time_range") else { return nil }
            return .portfolio(equity: equity, currency: currency, gainAbs: gainAbs, gainPct: gainPct, timeRange: timeRange)

        case .funding:
            guard let balance = data.decimalValue("balance"),
                  let apy = data.decimalValue("apy"),
                  let buyingPower = data.decimalValue("buying_power") else { return nil }
            return .funding(balance: balance, apy: apy, buyingPower: buyingPower)

        case .holdings:
            guard case .array(let rows)? = data["holdings"] else { return nil }
            return .holdings(holdings: rows.compactMap { row in
                guard case .object(let h) = row,
                      let ticker = h.stringValue("ticker"),
                      let marketValue = h.decimalValue("market_value") else { return nil }
                return HoldingSummary(ticker: ticker, marketValue: marketValue, unrealizedPl: h.decimalValue("unrealized_pl"))
            })

        case .radar:
            guard case .array(let rows)? = data["items"] else { return nil }
            return .radar(items: rows.compactMap { row in
                guard case .object(let r) = row,
                      let ticker = r.stringValue("ticker"),
                      let description = r.stringValue("description"),
                      let price = r.stringValue("price"),
                      let changePercent = r.stringValue("change_percent"),
                      let isPositive = r.boolValue("is_positive") else { return nil }
                return RadarSummary(ticker: ticker, description: description, price: price, changePercent: changePercent, isPositive: isPositive)
            })
        }
    }
}

private extension Dictionary where Key == String, Value == JSONValue {
    func stringValue(_ key: String) -> String? {
        if case .string(let s)? = self[key] { return s }
        return nil
    }

    /// Decimal-on-the-wire: values arrive as JSON strings, parsed back to
    /// `Decimal`. A non-string or unparseable value yields `nil`.
    func decimalValue(_ key: String) -> Decimal? {
        if case .string(let s)? = self[key] { return Decimal(string: s) }
        return nil
    }

    func boolValue(_ key: String) -> Bool? {
        if case .bool(let b)? = self[key] { return b }
        return nil
    }
}

struct HoldingSummary: Identifiable, Equatable, Sendable {
    var id: String { ticker }
    let ticker: String
    let marketValue: Decimal
    let unrealizedPl: Decimal?
}

struct RadarSummary: Identifiable, Equatable, Sendable {
    var id: String { ticker }
    let ticker: String
    let description: String
    let price: String
    let changePercent: String
    let isPositive: Bool
}
