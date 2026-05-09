import XCTest
@testable import Sevino

@MainActor
final class PortfolioChartViewScrubLabelTests: XCTestCase {

    func test_scrubLabel_returnsFormattedValue_whenLengthsMatch() {
        let result = PortfolioChartView.scrubLabel(
            at: 1,
            values: [Decimal(800), Decimal(900), Decimal(1000)],
            expectedCount: 3,
            currency: "USD"
        )

        XCTAssertEqual(result, Decimal(900).asCurrency(currencyCode: "USD"))
    }

    func test_scrubLabel_returnsNil_whenValuesShorterThanPoints() {
        let result = PortfolioChartView.scrubLabel(
            at: 2,
            values: [Decimal(800), Decimal(900)],
            expectedCount: 3,
            currency: "USD"
        )

        XCTAssertNil(result)
    }

    func test_scrubLabel_returnsNil_whenValuesLongerThanPoints() {
        let result = PortfolioChartView.scrubLabel(
            at: 1,
            values: [Decimal(800), Decimal(900), Decimal(1000)],
            expectedCount: 2,
            currency: "USD"
        )

        XCTAssertNil(result)
    }

    func test_scrubLabel_returnsNil_whenValuesEmpty() {
        let result = PortfolioChartView.scrubLabel(
            at: 0,
            values: [],
            expectedCount: 3,
            currency: "USD"
        )

        XCTAssertNil(result)
    }

    func test_scrubLabel_returnsNil_whenIndexOutOfRange() {
        let result = PortfolioChartView.scrubLabel(
            at: 5,
            values: [Decimal(800), Decimal(900), Decimal(1000)],
            expectedCount: 3,
            currency: "USD"
        )

        XCTAssertNil(result)
    }

    func test_scrubLabel_returnsNil_whenIndexNegative() {
        let result = PortfolioChartView.scrubLabel(
            at: -1,
            values: [Decimal(800), Decimal(900), Decimal(1000)],
            expectedCount: 3,
            currency: "USD"
        )

        XCTAssertNil(result)
    }

    func test_scrubLabel_usesCurrencyCode() {
        let usd = PortfolioChartView.scrubLabel(
            at: 0,
            values: [Decimal(1000)],
            expectedCount: 1,
            currency: "USD"
        )
        let eur = PortfolioChartView.scrubLabel(
            at: 0,
            values: [Decimal(1000)],
            expectedCount: 1,
            currency: "EUR"
        )

        XCTAssertNotNil(usd)
        XCTAssertNotNil(eur)
        XCTAssertNotEqual(usd, eur, "Currency code must affect formatting")
    }
}

@MainActor
final class PortfolioChartViewScrubDateLabelTests: XCTestCase {

    /// 2026-03-05 14:30 UTC = 9:30 AM ET (market open) — gives stable
    /// well-known wall-clock values for tests regardless of when CI runs.
    private let marketOpenDate = Date(timeIntervalSince1970: 1772893800)
    private let marketTZ = TimeZone(identifier: "America/New_York")!

    private func dates(_ count: Int) -> [Date] {
        (0..<count).map { marketOpenDate.addingTimeInterval(TimeInterval($0 * 60)) }
    }

    // MARK: - Length-mismatch / out-of-range fallbacks

    func test_scrubDateLabel_returnsNil_whenDatesShorterThanPoints() {
        XCTAssertNil(PortfolioChartView.scrubDateLabel(
            at: 2, dates: dates(2), expectedCount: 3, range: .oneDay
        ))
    }

    func test_scrubDateLabel_returnsNil_whenDatesLongerThanPoints() {
        XCTAssertNil(PortfolioChartView.scrubDateLabel(
            at: 1, dates: dates(3), expectedCount: 2, range: .oneDay
        ))
    }

    func test_scrubDateLabel_returnsNil_whenDatesEmpty() {
        XCTAssertNil(PortfolioChartView.scrubDateLabel(
            at: 0, dates: [], expectedCount: 3, range: .oneDay
        ))
    }

    func test_scrubDateLabel_returnsNil_whenIndexOutOfRange() {
        XCTAssertNil(PortfolioChartView.scrubDateLabel(
            at: 5, dates: dates(3), expectedCount: 3, range: .oneDay
        ))
    }

    func test_scrubDateLabel_returnsNil_whenIndexNegative() {
        XCTAssertNil(PortfolioChartView.scrubDateLabel(
            at: -1, dates: dates(3), expectedCount: 3, range: .oneDay
        ))
    }

    // MARK: - Format per range (Apple Stocks pattern)

    func test_scrubDateLabel_oneDay_showsTimeOnly_inMarketTZ() {
        // marketOpenDate = 9:30 AM ET → label should reflect that time
        // (not UTC, which would be 14:30, and not local).
        let result = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneDay
        )

        XCTAssertNotNil(result)
        // Compare against expected style format in the same TZ — independent
        // of the simulator's locale settings.
        let expected = marketOpenDate.formatted(
            Date.FormatStyle(timeZone: marketTZ).hour().minute()
        )
        XCTAssertEqual(result, expected)
    }

    func test_scrubDateLabel_oneWeek_showsWeekdayAndTime() {
        let result = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneWeek
        )

        let expected = marketOpenDate.formatted(
            Date.FormatStyle(timeZone: marketTZ)
                .weekday(.abbreviated).hour().minute()
        )
        XCTAssertEqual(result, expected)
    }

    func test_scrubDateLabel_oneMonth_showsMonthAndDay() {
        let result = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneMonth
        )

        let expected = marketOpenDate.formatted(
            Date.FormatStyle(timeZone: marketTZ).month(.abbreviated).day()
        )
        XCTAssertEqual(result, expected)
    }

    func test_scrubDateLabel_oneMonth_threeMonths_shareNoYearFormat() {
        // 1M and 3M are guaranteed same-year (max 90 days back), so the
        // year is omitted to keep the label compact.
        let oneM = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneMonth
        )
        let threeM = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .threeMonths
        )

        XCTAssertEqual(oneM, threeM)
    }

    func test_scrubDateLabel_sixMonths_ytd_oneYear_shareYearFormat() {
        // 6M can cross Jan 1, YTD/1Y always could — all three include the
        // 4-digit year for disambiguation.
        let sixM = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .sixMonths
        )
        let ytd = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .ytd
        )
        let oneY = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneYear
        )

        XCTAssertEqual(sixM, ytd)
        XCTAssertEqual(ytd, oneY)
    }

    func test_scrubDateLabel_oneMonth_omitsYear_sixMonths_includesYear() {
        // The 1M/3M vs 6M+ split is the load-bearing rule of this format
        // table. Pin it explicitly so a future "let's just always show
        // the year" tweak fails this test.
        let oneM = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneMonth
        )
        let sixM = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .sixMonths
        )

        XCTAssertNotEqual(oneM, sixM)
    }

    func test_scrubDateLabel_oneYear_includesYear() {
        let result = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneYear
        )

        // 4-digit year for consistency with ALL ("Mar 2026"). 1Y is rare
        // enough that the extra two characters aren't worth the
        // visual inconsistency of "Mar 5, '26" vs "Mar 2026".
        let expected = marketOpenDate.formatted(
            Date.FormatStyle(timeZone: marketTZ)
                .month(.abbreviated).day().year()
        )
        XCTAssertEqual(result, expected)
    }

    func test_scrubDateLabel_all_showsMonthAndYearOnly() {
        let result = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .all
        )

        let expected = marketOpenDate.formatted(
            Date.FormatStyle(timeZone: marketTZ).month(.abbreviated).year()
        )
        XCTAssertEqual(result, expected)
    }

    func test_scrubDateLabel_oneDayAndAll_haveDifferentFormats() {
        let oneDay = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .oneDay
        )
        let all = PortfolioChartView.scrubDateLabel(
            at: 0, dates: [marketOpenDate], expectedCount: 1, range: .all
        )

        XCTAssertNotNil(oneDay)
        XCTAssertNotNil(all)
        XCTAssertNotEqual(oneDay, all,
                          "1D (time) and ALL (month+year) must produce different labels")
    }
}
