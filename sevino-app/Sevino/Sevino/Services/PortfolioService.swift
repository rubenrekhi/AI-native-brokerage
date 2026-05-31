import Foundation

/// Raw portfolio data for the home card.
///
/// Money/percent fields stay as `Decimal`; formatting belongs to the view
/// (`Utils/NumberFormatting.swift`). `chartPoints` are unitless 0…1 values
/// for `PortfolioChartView`'s shape; `chartValues` are the raw equity
/// values parallel to `chartPoints`, used by the chart's scrub label so it
/// reflects the actual price at that index. `chartDates` are the bar
/// timestamps parallel to the same index, formatted by the chart's scrub
/// date label.
struct PortfolioSnapshot: Equatable {
    let equity: Decimal
    let currency: String
    let gainAbs: Decimal
    let gainPct: Decimal             // fraction (0.27336), NOT 27.336
    let chartPoints: [Double]
    let chartValues: [Decimal]
    let chartDates: [Date]
}

/// Pill-only subset of `PortfolioSnapshot`. Returned by `fetchSnapshot()` for
/// the 5-min auto-refresh timer, which updates the equity number on the pill
/// without re-fetching the (cheap-but-pointless-on-the-pill) history bars.
struct PortfolioPillUpdate: Equatable {
    let equity: Decimal
    let currency: String
    let dailyChangeAbs: Decimal
    let dailyChangePct: Decimal
}

/// Protocol for fetching portfolio data — enables mocking in previews and tests.
protocol PortfolioServiceProtocol: Sendable {
    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot
    func fetchSnapshot() async throws -> PortfolioPillUpdate
}

/// Calls `GET /v1/portfolio/snapshot` and `GET /v1/portfolio/history?range=...`
/// in parallel and folds them into a `PortfolioSnapshot`.
///
/// Gain source rule (kept consistent across the app):
/// - `.oneDay` → snapshot's `daily_change_*` (live, prev-close baseline)
/// - others   → history's `gain_*` (server-computed range-relative)
final class PortfolioService: PortfolioServiceProtocol {
    static let shared = PortfolioService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func fetchPortfolio(for range: TimeRange) async throws -> PortfolioSnapshot {
        async let snap: PortfolioSnapshotDTO = api.get("/v1/portfolio/snapshot")
        async let hist: PortfolioHistoryDTO  = api.get(Self.historyPath(for: range))
        let (snapshot, history) = try await (snap, hist)
        return Self.makeSnapshot(snapshot: snapshot, history: history, range: range)
    }

    func fetchSnapshot() async throws -> PortfolioPillUpdate {
        let dto: PortfolioSnapshotDTO = try await api.get("/v1/portfolio/snapshot")
        return PortfolioPillUpdate(
            equity: dto.equity,
            currency: dto.currency,
            dailyChangeAbs: dto.dailyChangeAbs,
            dailyChangePct: dto.dailyChangePct
        )
    }

    static func historyPath(for range: TimeRange) -> String {
        var components = URLComponents()
        components.path = "/v1/portfolio/history"
        components.queryItems = [URLQueryItem(name: "range", value: range.rawValue)]
        return components.string ?? "/v1/portfolio/history?range=\(range.rawValue)"
    }

    static func makeSnapshot(
        snapshot: PortfolioSnapshotDTO,
        history: PortfolioHistoryDTO,
        range: TimeRange
    ) -> PortfolioSnapshot {
        let (gainAbs, gainPct) = gain(snapshot: snapshot, history: history, range: range)
        let rawValues = history.points.map { $0.v }
        let rawDates = history.points.map { $0.t }
        return PortfolioSnapshot(
            equity: snapshot.equity,
            currency: snapshot.currency,
            gainAbs: gainAbs,
            gainPct: gainPct,
            chartPoints: normalize(rawValues),
            chartValues: rawValues,
            chartDates: rawDates
        )
    }

    private static func gain(
        snapshot: PortfolioSnapshotDTO,
        history: PortfolioHistoryDTO,
        range: TimeRange
    ) -> (abs: Decimal, pct: Decimal) {
        switch range {
        case .oneDay:
            return (snapshot.dailyChangeAbs, snapshot.dailyChangePct)
        default:
            return (history.gainAbs, history.gainPct)
        }
    }

    /// Normalizes raw equity values to 0…1 for `PortfolioChartView`.
    /// Returns `[]` for empty input, single point, or perfectly flat lines —
    /// `PortfolioChartView` already renders an empty `Path()` for `count ≤ 1`.
    static func normalize(_ values: [Decimal]) -> [Double] {
        guard values.count >= 2 else { return [] }
        let doubles = values.map { ($0 as NSDecimalNumber).doubleValue }
        guard let lo = doubles.min(), let hi = doubles.max(), hi > lo else { return [] }
        let span = hi - lo
        return doubles.map { ($0 - lo) / span }
    }
}
