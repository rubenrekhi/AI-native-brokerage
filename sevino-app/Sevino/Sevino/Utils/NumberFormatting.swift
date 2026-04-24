import Foundation

extension Decimal {
    /// "$1,084.92"
    func asCurrency(locale: Locale = .current) -> String {
        currencyFormatter(locale: locale, signed: false).string(from: nsDecimal) ?? "\(self)"
    }

    /// "+$232.82" or "-$1,049.32"
    func asSignedCurrency(locale: Locale = .current) -> String {
        currencyFormatter(locale: locale, signed: true).string(from: nsDecimal) ?? "\(self)"
    }

    /// "+27.31%" or "-8.38%"  (input is a factor of 1)
    func asSignedPercent(locale: Locale = .current) -> String {
        percentFormatter(locale: locale, signed: true).string(from: nsDecimal) ?? "\(self)"
    }

    /// "57" or "0.125"
    func asShareCount() -> String {
        shareFormatter.string(from: nsDecimal) ?? "\(self)"
    }

    private var nsDecimal: NSDecimalNumber { NSDecimalNumber(decimal: self) }
}

private let _cache = NSCache<NSString, NumberFormatter>()

private func currencyFormatter(locale: Locale, signed: Bool) -> NumberFormatter {
    let key = "cur-\(signed)-\(locale.identifier)" as NSString
    if let f = _cache.object(forKey: key) { return f }
    let f = NumberFormatter()
    f.numberStyle = .currency
    f.locale = locale
    f.currencyCode = "USD"
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

private let shareFormatter: NumberFormatter = {
    let f = NumberFormatter()
    f.numberStyle = .decimal
    f.minimumFractionDigits = 0
    f.maximumFractionDigits = 9
    f.usesGroupingSeparator = true
    return f
}()
