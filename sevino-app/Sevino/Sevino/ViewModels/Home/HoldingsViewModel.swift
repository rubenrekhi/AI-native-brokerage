import Foundation

@Observable
final class HoldingsViewModel {
    private let service: any HoldingsServiceProtocol

    private(set) var holdings: [Holding] = []
    private(set) var displayOption: HoldingsDisplayOption = .totalValue
    private(set) var sortOption: HoldingsSortOption = .highToLow

    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any HoldingsServiceProtocol = PlaceholderHoldingsService.shared) {
        self.service = service
    }

    func loadHoldings() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            holdings = try await service.fetchHoldings()
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func setDisplayOption(_ option: HoldingsDisplayOption) {
        displayOption = option
    }

    func setSortOption(_ option: HoldingsSortOption) {
        sortOption = option
    }

    func clearError() {
        error = nil
    }
}
