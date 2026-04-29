import Foundation

@Observable
final class HoldingsViewModel {
    private let service: any HoldingsServiceProtocol

    private(set) var holdings: [Holding] = []
    private(set) var displayOption: HoldingsDisplayOption = .totalValue
    private(set) var sortOption: HoldingsSortOption = .highToLow

    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any HoldingsServiceProtocol = APIHoldingsService.shared) {
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

    /// Pull-to-refresh entry point — same operation as `loadHoldings`, named
    /// to match the F4.9 spec and read clearly at the call site.
    func reload() async {
        await loadHoldings()
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
