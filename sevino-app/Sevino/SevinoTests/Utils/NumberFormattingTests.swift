import XCTest
@testable import Sevino

@MainActor
final class NumberFormattingTests: XCTestCase {

    private let usLocale = Locale(identifier: "en_US")
    private let gbLocale = Locale(identifier: "en_GB")
    private let deLocale = Locale(identifier: "de_DE")

    // MARK: - asCurrency

    func testAsCurrency_positive_formatsWithDollarSign() {
        let value = Decimal(string: "1084.92")!
        XCTAssertEqual(value.asCurrency(locale: usLocale), "$1,084.92")
    }

    // MARK: - asSignedCurrency

    func testAsSignedCurrency_positive_prefixesPlus() {
        let value = Decimal(string: "232.82")!
        XCTAssertEqual(value.asSignedCurrency(locale: usLocale), "+$232.82")
    }

    func testAsSignedCurrency_negative_usesDefaultMinus() {
        let value = Decimal(string: "-1049.32")!
        XCTAssertEqual(value.asSignedCurrency(locale: usLocale), "-$1,049.32")
    }

    // MARK: - asSignedPercent

    func testAsSignedPercent_positive_prefixesPlus() {
        let value = Decimal(string: "0.2731")!
        XCTAssertEqual(value.asSignedPercent(locale: usLocale), "+27.31%")
    }

    func testAsSignedPercent_negative_usesDefaultMinus() {
        let value = Decimal(string: "-0.0838")!
        XCTAssertEqual(value.asSignedPercent(locale: usLocale), "-8.38%")
    }

    // MARK: - asShareCount

    func testAsShareCount_wholeShares_noDecimals() {
        let value = Decimal(string: "57")!
        XCTAssertEqual(value.asShareCount(), "57")
    }

    func testAsShareCount_fractional_preservesSignificantDigits() {
        let value = Decimal(string: "0.125")!
        XCTAssertEqual(value.asShareCount(), "0.125")
    }

    func testAsShareCount_germanLocale_usesCommaDecimal() {
        let value = Decimal(string: "0.125")!
        XCTAssertEqual(value.asShareCount(locale: deLocale), "0,125")
    }

    func testAsShareCount_truncatesPrecisionPastFourDecimals() {
        // Backend keeps full Alpaca precision (up to 9 dp); the UI rounds to
        // 4 dp so the user doesn't see "0.011801359 shares" in the holdings
        // modal. If a future surface needs full precision (e.g. trade
        // confirmation), it should add a separate formatter rather than
        // change this one.
        let value = Decimal(string: "0.011801359")!
        XCTAssertEqual(value.asShareCount(), "0.0118")
    }

    // MARK: - Locale override

    func testAsCurrency_gbLocale_stillUsesDollarForUSD() {
        // currencyCode is pinned to USD; a non-US locale should still render
        // USD (not GBP) but may format with locale-specific grouping.
        let value = Decimal(string: "1084.92")!
        let output = value.asCurrency(locale: gbLocale)
        XCTAssertTrue(
            output.contains("1,084.92"),
            "Expected output to contain 1,084.92, got \(output)"
        )
        // Must contain a USD indicator ($ or US$), never a £.
        XCTAssertFalse(output.contains("£"))
    }
}
