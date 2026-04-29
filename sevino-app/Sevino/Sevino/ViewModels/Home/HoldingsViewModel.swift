import Foundation

@Observable
final class HoldingsViewModel {
    private let service: any HoldingsServiceProtocol

    private(set) var holdings: [PortfolioHolding] = []
    private(set) var accountStatus: String = ""
    private(set) var displayOption: HoldingsDisplayOption = .totalValue
    private(set) var sortOption: HoldingsSortOption = .highToLow

    private(set) var isLoading = false
    private(set) var error: String?

    init(service: any HoldingsServiceProtocol = APIHoldingsService.shared) {
        self.service = service
    }

    /// Mirrors `PortfolioViewModel.loadSnapshot`: on `ACCOUNT_NOT_ACTIVE`,
    /// parses the wrapped `account_status` into `accountStatus` so the
    /// holdings modal renders the pending/rejected message instead of a
    /// generic error. Stale-while-error suppresses refresh-failure noise.
    func loadHoldings() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let result = try await service.fetchHoldings()
            holdings = result.holdings
            accountStatus = result.accountStatus
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
