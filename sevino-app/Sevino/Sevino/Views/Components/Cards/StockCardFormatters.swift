import Foundation

/// Display-string helpers for `SingleStockCard`'s stats grid. Each
/// formatter takes a raw wire value (typically a decimal string the
/// backend left untouched per the decimal-on-the-wire convention) and
/// returns a locale-aware display string — or `nil` for unparseable
/// input so the caller can drop the row entirely. Extracted out of the
/// view so the formatter branches (T/B/M/K boundaries, fraction-as-percent,
/// nil propagation) are unit-testable without spinning up SwiftUI.
enum StockCardFormatters {

    /// "$184.92" — USD-currency style. Returns nil for unparseable input.
    static func currency(_ raw: String?) -> String? {
        guard let raw, let value = Decimal(string: raw) else { return nil }
        return value.formatted(
            .currency(code: "USD").precision(.fractionLength(2))
        )
    }

    /// "23.45" — plain two-decimal formatting, used for ratios where a
    /// currency symbol would mislead (P/E, beta).
    static func decimal(_ raw: String?) -> String? {
        guard let raw, let value = Decimal(string: raw) else { return nil }
        return value.formatted(.number.precision(.fractionLength(2)))
    }

    /// "+0.48%" — fraction in, signed percent out. FMP delivers
    /// dividend yield as a fraction (0.0048 = 0.48%), matching the
    /// `change_pct` convention on the block.
    static func percent(_ raw: String?) -> String? {
        guard let raw, let value = Decimal(string: raw) else { return nil }
        return value.formatted(
            .percent.sign(strategy: .always()).precision(.fractionLength(2))
        )
    }

    /// "$3.5T" / "1.5M" — compact notation for big counts. `currency`
    /// flag prefixes with the locale's currency symbol (market cap);
    /// without it the value renders raw (volume). `nil` only when the
    /// input itself is `nil` — a literal zero is a valid value and
    /// renders as "0" / "$0", not dropped.
    static func compactInt(_ raw: Int?, currency: Bool) -> String? {
        guard let raw else { return nil }
        if currency {
            return Decimal(raw).formatted(
                .currency(code: "USD").notation(.compactName).precision(.fractionLength(0...1))
            )
        }
        return raw.formatted(.number.notation(.compactName))
    }
}
