import Foundation

@Observable
final class PortfolioViewModel {
    private let service: any PortfolioServiceProtocol

    private(set) var equity: Decimal = 0
    private(set) var currency: String = "USD"
    private(set) var gainAbs: Decimal = 0
    private(set) var gainPct: Decimal = 0
    private(set) var chartPoints: [Double] = []
    private(set) var chartValues: [Decimal] = []
    private(set) var chartDates: [Date] = []
    private(set) var selectedTimeRange: TimeRange = .oneMonth
    private(set) var hasLoaded: Bool = false

    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any PortfolioServiceProtocol = PortfolioService.shared) {
        self.service = service
    }

    var periodLabel: String { selectedTimeRange.periodLabel }

    /// Sets the selected time range synchronously so the UI updates immediately.
    /// Callers should trigger the fetch separately (e.g. via `.task(id:)`), which
    /// gives SwiftUI ownership of cancellation when ranges change rapidly.
    func setTimeRange(_ range: TimeRange) {
        selectedTimeRange = range
    }

    func loadPortfolio() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let snapshot = try await service.fetchPortfolio(for: selectedTimeRange)
            equity = snapshot.equity
            currency = snapshot.currency
            gainAbs = snapshot.gainAbs
            gainPct = snapshot.gainPct
            chartPoints = snapshot.chartPoints
            chartValues = snapshot.chartValues
            chartDates = snapshot.chartDates
            hasLoaded = true
        } catch let caughtError {
            error = caughtError.localizedDescription
            // hasLoaded stays whatever it was — last-good data stays visible behind alert.
        }
    }

    func clearError() {
        error = nil
    }
}
