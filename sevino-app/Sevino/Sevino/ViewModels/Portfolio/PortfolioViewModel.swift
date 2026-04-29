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

    /// Latest snapshot's `accountStatus` (e.g. `"ACTIVE"`, `"APPROVAL_PENDING"`).
    /// Empty until the first successful snapshot fetch — views should treat
    /// empty as "still loading" rather than rendering numeric values.
    private(set) var accountStatus: String = ""

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

    /// Fetches just the snapshot.
    ///
    /// On `ACCOUNT_NOT_ACTIVE` (the 409 raised by the backend's
    /// `get_alpaca_account_context` dependency), parses the wrapped
    /// `account_status` out of `APIError.detail` so the pending/rejected UI
    /// can render — without this, non-ACTIVE users would only see a generic
    /// error toast.
    ///
    /// Stale-while-error: errors only surface when we have no status info at
    /// all. After any successful fetch (or a parsed 409), refresh failures
    /// stay silent so the last good value remains on screen.
    func loadSnapshot() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot = try await service.fetchPortfolio(for: selectedTimeRange)
            displayValue = snapshot.displayValue
            isDown = snapshot.isDown
            gainText = snapshot.gainText
            accountStatus = snapshot.accountStatus
        } catch let caughtError {
            if let apiError = caughtError as? APIError,
               apiError.code == APIError.Code.accountNotActive,
               let status = apiError.detail?["account_status"]?.stringValue {
                accountStatus = status
            }
            if accountStatus.isEmpty {
                error = caughtError.localizedDescription
            }
        }
    }

    /// Fetches just the history series for `selectedTimeRange`. History errors
    /// silently leave the chart empty — chart skeleton/empty-state polish is
    /// tracked as a follow-up. Wire this to `.task(id: selectedTimeRange)` so
    /// range changes don't refetch the snapshot and the pill numbers stay stable.
    func loadHistory() async {
        if let history = try? await historyService.fetchHistory(for: selectedTimeRange) {
            chartPoints = history.chartPoints
        }
    }

    func clearError() {
        error = nil
    }
}
