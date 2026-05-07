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
            applySort()
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func setDisplayOption(_ option: HoldingsDisplayOption) {
        displayOption = option
        applySort()
    }

    func setSortOption(_ option: HoldingsSortOption) {
        sortOption = option
        applySort()
    }

    func clearError() {
        error = nil
    }

    /// Reorder `holdings` based on the current `(displayOption, sortOption)`
    /// pair. CASH rows are always pinned to the top regardless of sort —
    /// the user's cash isn't a "position" they should compare against.
    private func applySort() {
        let cashRows = holdings.filter { $0.isCash }
        let positionRows = holdings.filter { !$0.isCash }
        holdings = cashRows + sortedPositions(positionRows)
    }

    private func sortedPositions(_ positions: [Holding]) -> [Holding] {
        switch sortOption {
        case .alphabetical:
            return positions.sorted { $0.ticker < $1.ticker }
        case .highToLow:
            return positions.sorted { sortKey(for: $0) > sortKey(for: $1) }
        case .lowToHigh:
            return positions.sorted { sortKey(for: $0) < sortKey(for: $1) }
        }
    }

    private func sortKey(for holding: Holding) -> Decimal {
        switch displayOption {
        case .allTimeReturn:
            return holding.unrealizedPl ?? 0
        case .todaysReturn:
            return holding.changeToday ?? 0
        case .totalValue:
            return holding.marketValue
        case .priceChange:
            return holding.changeTodayPercent ?? 0
        }
    }
}
