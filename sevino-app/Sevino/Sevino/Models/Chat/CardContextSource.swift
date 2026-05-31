import Foundation

struct CardContextSource: Codable, Equatable, Sendable {
    let symbol: String?
    let kind: String

    init(symbol: String?, kind: String) {
        self.symbol = symbol?.isEmpty == false ? symbol : nil
        self.kind = kind
    }

    init?(digestCard: ChatDigestCard) {
        guard case .string(let kind) = digestCard.payload["kind"] else { return nil }
        self.init(symbol: Self.firstSymbol(in: digestCard.payload), kind: kind)
    }

    var localizedKind: String {
        switch kind {
        case "earnings_result", "upcoming_earnings":
            return L10n.Chat.cardKindEarnings
        case "pending_order_activity":
            return L10n.Chat.cardKindOrderActivity
        default:
            return kind.replacingOccurrences(of: "_", with: " ")
        }
    }

    var displayText: String {
        if let symbol {
            return L10n.Chat.cardContextSourceWithSymbol(symbol, localizedKind)
        }
        return L10n.Chat.cardContextSourceWithoutSymbol(localizedKind)
    }

    private static func firstSymbol(in payload: [String: JSONValue]) -> String? {
        if case .array(let symbols)? = payload["related_symbols"],
           case .string(let symbol)? = symbols.first {
            return symbol
        }
        if case .array(let symbols)? = payload["relatedSymbols"],
           case .string(let symbol)? = symbols.first {
            return symbol
        }
        if case .string(let symbol)? = payload["symbol"] {
            return symbol
        }
        return nil
    }
}
