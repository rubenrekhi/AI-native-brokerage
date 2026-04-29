import Foundation

@Observable
final class PortfolioViewModel {
    private let service: any PortfolioServiceProtocol
    private let historyService: any PortfolioHistoryServiceProtocol

    private(set) var displayValue = "—"
    private(set) var isDown = false
    private(set) var gainText = ""
    private(set) var chartPoints: [Double] = []
    private(set) var selectedTimeRange: TimeRange = .oneMonth

    private(set) var isLoading = false
    private(set) var error: String?

    init(
        service: any PortfolioServiceProtocol = APIPortfolioService.shared,
        historyService: any PortfolioHistoryServiceProtocol = APIPortfolioHistoryService.shared
    ) {
        self.service = service
        self.historyService = historyService
    }

    var periodLabel: String { selectedTimeRange.periodLabel }

    /// Sets the selected time range synchronously so the UI updates immediately.
    /// Callers should trigger the fetch separately (e.g. via `.task(id:)`), which
    /// gives SwiftUI ownership of cancellation when ranges change rapidly.
    func setTimeRange(_ range: TimeRange) {
        selectedTimeRange = range
    }

    /// Fetches snapshot (range-agnostic pill numbers) and history (range-scoped
    /// chart) in parallel. Use this for initial loads and explicit retries.
    func loadPortfolio() async {
        async let snap: Void = loadSnapshot()
        async let hist: Void = loadHistory()
        _ = await (snap, hist)
    }

    /// Fetches just the snapshot. Snapshot errors surface to the user via `error`.
    func loadSnapshot() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot = try await service.fetchPortfolio(for: selectedTimeRange)
            displayValue = snapshot.displayValue
            isDown = snapshot.isDown
            gainText = snapshot.gainText
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    /// Fetches just the history series for `selectedTimeRange`. History errors
    /// silently leave the chart empty — F4.10 will add explicit empty/error UI.
    /// Wire this to `.task(id: selectedTimeRange)` so range changes don't refetch
    /// the snapshot and the pill numbers stay stable.
    func loadHistory() async {
        if let history = try? await historyService.fetchHistory(for: selectedTimeRange) {
            chartPoints = history.chartPoints
        }
    }

    func clearError() {
        error = nil
    }
}
