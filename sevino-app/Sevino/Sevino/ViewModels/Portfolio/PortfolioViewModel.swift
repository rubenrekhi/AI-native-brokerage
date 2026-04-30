import Foundation

@Observable
final class PortfolioViewModel {
    private let service: any PortfolioServiceProtocol

    private(set) var displayValue = "—"
    private(set) var isDown = false
    private(set) var gainText = ""
    private(set) var chartPoints: [Double] = []
    private(set) var selectedTimeRange: TimeRange = .oneMonth

    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any PortfolioServiceProtocol = PlaceholderPortfolioService.shared) {
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
            displayValue = snapshot.displayValue
            isDown = snapshot.isDown
            gainText = snapshot.gainText
            chartPoints = snapshot.chartPoints
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }
}
