import Foundation

extension Decimal {
    /// "$1,084.92"
    func asCurrency(currencyCode: String = "USD", locale: Locale = .current) -> String {
        currencyFormatter(currencyCode: currencyCode, locale: locale, signed: false)
            .string(from: nsDecimal) ?? "\(self)"
    }

    /// "+$232.82" or "-$1,049.32"
    func asSignedCurrency(currencyCode: String = "USD", locale: Locale = .current) -> String {
        currencyFormatter(currencyCode: currencyCode, locale: locale, signed: true)
            .string(from: nsDecimal) ?? "\(self)"
    }

    /// "+27.31%" or "-8.38%"  (input is a factor of 1)
    func asSignedPercent(locale: Locale = .current) -> String {
        percentFormatter(locale: locale, signed: true).string(from: nsDecimal) ?? "\(self)"
    }

    /// "27.31%" / "0.03%" / "100%" — unsigned, for ratios and weights
    /// (input is a factor of 1). `maximumFractionDigits` trims trailing
    /// precision so a sector weight reads "30%" while an expense ratio
    /// keeps "0.03%".
    func asPercent(maximumFractionDigits: Int = 2, locale: Locale = .current) -> String {
        plainPercentFormatter(locale: locale, maximumFractionDigits: maximumFractionDigits)
            .string(from: nsDecimal) ?? "\(self)"
    }

    /// "$3.50T" / "$184.0B" / "$950.0M" — compact magnitude for large money
    /// values (market cap, AUM). Display-only; the magnitude rounding is
    /// intentionally lossy, so never feed the result back into a calculation.
    func asAbbreviatedCurrency(locale: Locale = .current) -> String {
        let value = nsDecimal.doubleValue
        let magnitude = Swift.abs(value)
        let sign = value < 0 ? "-" : ""
        let scaled: Double
        let suffix: String
        switch magnitude {
        case 1e12...: scaled = magnitude / 1e12; suffix = "T"
        case 1e9...: scaled = magnitude / 1e9; suffix = "B"
        case 1e6...: scaled = magnitude / 1e6; suffix = "M"
        case 1e3...: scaled = magnitude / 1e3; suffix = "K"
        default: return asCurrency(locale: locale)
        }
        let digits = scaled >= 100 ? 0 : (scaled >= 10 ? 1 : 2)
        let number = abbreviatedFormatter(locale: locale, fractionDigits: digits)
            .string(from: NSNumber(value: scaled)) ?? "\(scaled)"
        return "\(sign)$\(number)\(suffix)"
    }

    /// "57" or "0.125"
    func asShareCount(locale: Locale = .current) -> String {
        shareFormatter(locale: locale).string(from: nsDecimal) ?? "\(self)"
    }

    private var nsDecimal: NSDecimalNumber { NSDecimalNumber(decimal: self) }
}

// `NSCache` is documented thread-safe; the cache is only mutated through its
// own atomic methods, so the global is safe to share across actors despite
// being non-`Sendable`.
nonisolated(unsafe) private let _cache = NSCache<NSString, NumberFormatter>()

private func currencyFormatter(currencyCode: String, locale: Locale, signed: Bool) -> NumberFormatter {
    let key = "cur-\(signed)-\(currencyCode)-\(locale.identifier)" as NSString
    if let f = _cache.object(forKey: key) { return f }
    let f = NumberFormatter()
    f.numberStyle = .currency
    f.locale = locale
    f.currencyCode = currencyCode
    // On non-en_US locales, USD renders as "US$1,084.92" by default. Sevino is
    // a USD-only product and we want a bare "$" everywhere; user locale still
    // drives separators (e.g. "1.084,92" in DE). For non-USD codes we keep
    // the locale-default symbol.
    if currencyCode == "USD" {
        f.currencySymbol = "$"
    }
    if signed { f.positivePrefix = f.plusSign + (f.currencySymbol ?? "$") }
    _cache.setObject(f, forKey: key)
    return f
}

private func percentFormatter(locale: Locale, signed: Bool) -> NumberFormatter {
    let key = "pct-\(signed)-\(locale.identifier)" as NSString
    if let f = _cache.object(forKey: key) { return f }
    let f = NumberFormatter()
    f.numberStyle = .percent
    f.locale = locale
    f.minimumFractionDigits = 2
    f.maximumFractionDigits = 2
    if signed { f.positivePrefix = f.plusSign }
    _cache.setObject(f, forKey: key)
    return f
}

private func plainPercentFormatter(locale: Locale, maximumFractionDigits: Int) -> NumberFormatter {
    let key = "pctplain-\(locale.identifier)-\(maximumFractionDigits)" as NSString
    if let f = _cache.object(forKey: key) { return f }
    let f = NumberFormatter()
    f.numberStyle = .percent
    f.locale = locale
    f.minimumFractionDigits = 0
    f.maximumFractionDigits = maximumFractionDigits
    _cache.setObject(f, forKey: key)
    return f
}

private func abbreviatedFormatter(locale: Locale, fractionDigits: Int) -> NumberFormatter {
    let key = "abbr-\(locale.identifier)-\(fractionDigits)" as NSString
    if let f = _cache.object(forKey: key) { return f }
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.locale = locale
    f.minimumFractionDigits = fractionDigits
    f.maximumFractionDigits = fractionDigits
    f.usesGroupingSeparator = false
    _cache.setObject(f, forKey: key)
    return f
}

private func shareFormatter(locale: Locale) -> NumberFormatter {
    let key = "share-\(locale.identifier)" as NSString
    if let f = _cache.object(forKey: key) { return f }
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.locale = locale
    f.minimumFractionDigits = 0
    f.maximumFractionDigits = 4
    f.usesGroupingSeparator = true
    _cache.setObject(f, forKey: key)
    return f
}
