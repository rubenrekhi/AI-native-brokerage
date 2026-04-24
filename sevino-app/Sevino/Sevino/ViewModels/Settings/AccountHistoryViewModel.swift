import Foundation

@Observable
final class AccountHistoryViewModel {
    private let fundingService: any FundingServiceProtocol

    private(set) var transfers: [TransferResponse] = []
    private(set) var isLoading = false
    private(set) var error: String?

    /// Bindable flag the view alerts on. Only true when we have cached
    /// transfers to fall back to — a first-load failure renders inline via
    /// `errorState` instead of an alert.
    var isShowingError: Bool {
        get { error != nil && !transfers.isEmpty }
        set { if !newValue { clearError() } }
    }

    init(fundingService: any FundingServiceProtocol = FundingService.shared) {
        self.fundingService = fundingService
    }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let fetched = try await fundingService.listTransfers()
            transfers = fetched.sorted { lhs, rhs in
                switch (lhs.createdAtDate, rhs.createdAtDate) {
                case let (l?, r?): return l > r
                case (_?, nil): return true
                case (nil, _?): return false
                default: return false
                }
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }
}
