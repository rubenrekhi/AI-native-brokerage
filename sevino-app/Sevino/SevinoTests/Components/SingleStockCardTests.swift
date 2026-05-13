import XCTest
@testable import Sevino

/**
 Unit tests for `SingleStockCard.chartInputs(for:)`.

 The helper is the load-bearing transform between wire-format `Bar`
 payloads and the three parallel arrays `PortfolioChartView` expects.
 Two invariants worth pinning explicitly:

 1. `points` and `dates` must stay parallel — the chart's scrub date
    label requires `dates.count == points.count` and silently degrades
    to no label otherwise, so on any timestamp parse failure we bail
    `dates` to `[]` instead of returning a shorter array.
 2. `points` are min-max scaled into `0...1`. The flat-series fallback
    centers the line at `0.5` so a single-bar payload (or all-equal
    closes) doesn't collapse to the chart's bottom edge.
 */
final class SingleStockCardChartInputsTests: XCTestCase {

    // MARK: - Empty / degenerate

    func testEmptyBarsYieldsEmptyArrays() {
        let result = SingleStockCard.chartInputs(for: [])

        XCTAssertEqual(result.points, [])
        XCTAssertEqual(result.values, [])
        XCTAssertEqual(result.dates, [])
    }

    func testSingleBarCentersAtHalf() {
        // min == max → fallback to 0.5 so the line stays visible. The
        // companion `values` still carries the raw close so a scrub
        // label can show the price.
        let result = SingleStockCard.chartInputs(for: [
            Bar(t: "2026-04-29T13:00:00Z", c: 184.92)
        ])

        XCTAssertEqual(result.points, [0.5])
        XCTAssertEqual(result.values, [Decimal(184.92)])
        XCTAssertEqual(result.dates.count, 1)
    }

    func testAllEqualClosesAlsoCentersAtHalf() {
        // Sparse markets or pre-open ticks can deliver identical closes
        // for several bars in a row; same fallback applies so the line
        // doesn't disappear.
        let bars: [Bar] = (0..<3).map {
            Bar(t: "2026-04-29T13:0\($0):00Z", c: 200.0)
        }

        let result = SingleStockCard.chartInputs(for: bars)

        XCTAssertEqual(result.points, [0.5, 0.5, 0.5])
    }

    // MARK: - Normalisation

    func testDistinctClosesAreMinMaxScaled() {
        // 180, 184, 188 → distance min=180, max=188, range=8.
        // Expect 0, 0.5, 1.0.
        let bars: [Bar] = [
            Bar(t: "2026-04-29T13:00:00Z", c: 180),
            Bar(t: "2026-04-29T13:01:00Z", c: 184),
            Bar(t: "2026-04-29T13:02:00Z", c: 188),
        ]

        let result = SingleStockCard.chartInputs(for: bars)

        XCTAssertEqual(result.points[0], 0.0, accuracy: 1e-9)
        XCTAssertEqual(result.points[1], 0.5, accuracy: 1e-9)
        XCTAssertEqual(result.points[2], 1.0, accuracy: 1e-9)
        XCTAssertEqual(result.values, [Decimal(180), Decimal(184), Decimal(188)])
    }

    // MARK: - ISO 8601 parsing

    func testTimestampsWithoutFractionalSecondsParse() {
        // Alpaca's bar timestamps come without fractional seconds:
        // "2026-04-29T13:30:00Z". The strict ISO8601 formatter rejects
        // these when `.withFractionalSeconds` is set, so the helper
        // falls back to a non-fractional formatter.
        let bars: [Bar] = [
            Bar(t: "2026-04-29T13:00:00Z", c: 180),
            Bar(t: "2026-04-29T13:01:00Z", c: 184),
        ]

        let result = SingleStockCard.chartInputs(for: bars)

        XCTAssertEqual(result.dates.count, 2)
    }

    func testTimestampsWithFractionalSecondsParse() {
        // FMP-routed bars sometimes include fractional seconds; the
        // helper accepts both formats.
        let bars: [Bar] = [
            Bar(t: "2026-04-29T13:00:00.500Z", c: 180),
            Bar(t: "2026-04-29T13:01:00.123Z", c: 184),
        ]

        let result = SingleStockCard.chartInputs(for: bars)

        XCTAssertEqual(result.dates.count, 2)
    }

    func testSingleMalformedTimestampBailsAllDates() {
        // One bad timestamp would otherwise produce `dates.count <
        // points.count`, and `PortfolioChartView.scrubDateLabel` returns
        // nil for the *entire* chart when lengths don't match. Pin the
        // bail-to-empty behaviour so a partial parse doesn't silently
        // blank labels for every position.
        let bars: [Bar] = [
            Bar(t: "2026-04-29T13:00:00Z", c: 180),
            Bar(t: "not a date", c: 184),
            Bar(t: "2026-04-29T13:02:00Z", c: 188),
        ]

        let result = SingleStockCard.chartInputs(for: bars)

        XCTAssertEqual(result.points.count, 3)
        XCTAssertEqual(result.values.count, 3)
        XCTAssertEqual(result.dates, [])
    }

    // MARK: - Parallel arrays

    func testPointsValuesDatesShareIndices() {
        // The three arrays index in lockstep with `bars`. Pin that the
        // helper never reorders.
        let bars: [Bar] = [
            Bar(t: "2026-04-29T13:00:00Z", c: 200),
            Bar(t: "2026-04-29T13:01:00Z", c: 100),
            Bar(t: "2026-04-29T13:02:00Z", c: 150),
        ]

        let result = SingleStockCard.chartInputs(for: bars)

        XCTAssertEqual(result.points.count, 3)
        XCTAssertEqual(result.values.count, 3)
        XCTAssertEqual(result.dates.count, 3)

        // First bar's close is the max → maps to 1.0; second is the min → 0.0.
        XCTAssertEqual(result.points[0], 1.0, accuracy: 1e-9)
        XCTAssertEqual(result.points[1], 0.0, accuracy: 1e-9)
        XCTAssertEqual(result.values[0], Decimal(200))
    }
}
