import XCTest
@testable import Sevino

/**
 Unit tests for `StockCardFormatters` — the display helpers
 `SingleStockCard.StockCardStatsGrid` calls to render each row of the
 expanded stats table.

 The formatters are the only place where raw FMP / Alpaca values
 (decimal-strings, ints, fractions) get coerced into user-facing
 strings, so the branching paths are worth pinning:

 * Currency / decimal / percent unparseable → `nil` so the row drops
 * Percent expects a fraction (FMP's dividend_yield convention)
 * `compactInt` ladder boundaries (T → B → M → K → raw) for both the
   currency-prefixed (market cap) and bare-number (volume) variants

 We assert on a stable `en_US` locale via `String(format:)`-style
 substring matches (rather than full string equality) because
 `FormatStyle`'s thousands separators / suffixes are locale-aware and
 we don't want test brittleness on CI machines with non-en_US
 defaults.
 */
final class StockCardFormattersTests: XCTestCase {

    // MARK: - currency

    func testCurrencyParsesValidDecimalString() {
        let result = StockCardFormatters.currency("184.92")
        XCTAssertNotNil(result)
        XCTAssertTrue(result?.contains("184.92") ?? false)
        XCTAssertTrue(result?.contains("$") ?? false)
    }

    func testCurrencyReturnsNilForNil() {
        XCTAssertNil(StockCardFormatters.currency(nil))
    }

    func testCurrencyReturnsNilForUnparseable() {
        XCTAssertNil(StockCardFormatters.currency("not a number"))
        XCTAssertNil(StockCardFormatters.currency(""))
    }

    // MARK: - decimal

    func testDecimalRoundsToTwoFractionDigits() {
        let result = StockCardFormatters.decimal("23.456")
        XCTAssertEqual(result, "23.46")
    }

    func testDecimalReturnsNilForUnparseable() {
        XCTAssertNil(StockCardFormatters.decimal(nil))
        XCTAssertNil(StockCardFormatters.decimal("n/a"))
    }

    // MARK: - percent (fraction → signed percent string)

    func testPercentAcceptsFraction() {
        // FMP delivers dividend yield as a fraction (0.0048 = 0.48%).
        let result = StockCardFormatters.percent("0.0048")
        XCTAssertNotNil(result)
        // Sign is always shown; "+" for positive.
        XCTAssertTrue(result?.contains("+") ?? false)
        XCTAssertTrue(result?.contains("%") ?? false)
    }

    func testPercentRenderSignedForNegativeFraction() {
        let result = StockCardFormatters.percent("-0.0148")
        XCTAssertNotNil(result)
        XCTAssertTrue(result?.contains("-") ?? false)
    }

    func testPercentReturnsNilForUnparseable() {
        XCTAssertNil(StockCardFormatters.percent(nil))
        XCTAssertNil(StockCardFormatters.percent("garbage"))
    }

    // MARK: - compactInt ladder boundaries

    func testCompactIntTrillions() {
        let result = StockCardFormatters.compactInt(3_500_000_000_000, currency: true)
        XCTAssertNotNil(result)
        XCTAssertTrue(result?.contains("T") ?? false)
        XCTAssertTrue(result?.contains("$") ?? false)
    }

    func testCompactIntBillions() {
        let result = StockCardFormatters.compactInt(2_300_000_000, currency: true)
        XCTAssertNotNil(result)
        XCTAssertTrue(result?.contains("B") ?? false)
    }

    func testCompactIntMillionsNonCurrency() {
        // Volume rows use the non-currency variant.
        let result = StockCardFormatters.compactInt(50_000_000, currency: false)
        XCTAssertNotNil(result)
        XCTAssertTrue(result?.contains("M") ?? false)
        XCTAssertFalse(result?.contains("$") ?? false)
    }

    func testCompactIntThousands() {
        let result = StockCardFormatters.compactInt(1_500, currency: false)
        XCTAssertNotNil(result)
        XCTAssertTrue(result?.contains("K") ?? false)
    }

    func testCompactIntBelowThousandRendersRaw() {
        // No compact suffix below the K boundary; FormatStyle just shows
        // the raw number for small magnitudes.
        let result = StockCardFormatters.compactInt(42, currency: false)
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.filter(\.isWholeNumber), "42")
    }

    func testCompactIntZeroIsLegitimateValue() {
        // The pre-FormatStyle implementation dropped zero volume rows
        // by treating 0 as "missing". A genuinely-zero volume (e.g.
        // pre-market for a thin issue) is a valid value — the row
        // should render rather than disappearing silently.
        let result = StockCardFormatters.compactInt(0, currency: false)
        XCTAssertNotNil(result)
        // String contains a "0" character.
        XCTAssertTrue(result?.contains("0") ?? false)
    }

    func testCompactIntNilReturnsNil() {
        // Only `nil` (FMP didn't return the field at all) collapses
        // to nil so the row drops. A zero value still renders.
        XCTAssertNil(StockCardFormatters.compactInt(nil, currency: false))
        XCTAssertNil(StockCardFormatters.compactInt(nil, currency: true))
    }
}
