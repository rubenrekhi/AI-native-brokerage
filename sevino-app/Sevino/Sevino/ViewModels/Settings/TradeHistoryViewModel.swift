import Foundation

@Observable
final class TradeHistoryViewModel {
    private let tradingService: any TradingServiceProtocol

    private(set) var orders: [OrderResponse] = []
    private(set) var positions: [PositionResponse] = []
    private(set) var isLoading = false
    private(set) var error: String?

    private var loadTask: Task<Void, Never>?

    var statusFilter: TradeStatusFilter = .all {
        didSet { reloadIfNeeded(oldValue: oldValue, newValue: statusFilter) }
    }
    var sideFilter: TradeSideFilter = .all {
        didSet { reloadIfNeeded(oldValue: oldValue, newValue: sideFilter) }
    }
    var timeframeFilter: TradeTimeframeFilter = .all {
        didSet { reloadIfNeeded(oldValue: oldValue, newValue: timeframeFilter) }
    }
    /// Symbol the user picked from the holdings filter, or `nil` for all
    /// holdings. The chip is constructed from `positions`.
    var holdingsFilter: String? = nil {
        didSet { reloadIfNeeded(oldValue: oldValue, newValue: holdingsFilter) }
    }

    /// Bindable flag the view alerts on. Only true when we have cached orders
    /// to fall back to — first-load failures render inline via `errorState`
    /// instead of an alert. Mirrors the AccountHistoryViewModel pattern.
    var isShowingError: Bool {
        get { error != nil && !orders.isEmpty }
        set { if !newValue { clearError() } }
    }

    /// After client-side filtering by status bucket. The API filters status to
    /// open/closed and the client narrows further: the "closed" family
    /// contains both completed (filled) and failed (canceled/rejected/expired),
    /// which the design surfaces as separate pills.
    var filteredOrders: [OrderResponse] {
        orders.filter { order in
            let bucketMatch: Bool
            switch statusFilter {
            case .all: bucketMatch = true
            case .pending: bucketMatch = order.statusKind == .pending
            case .completed: bucketMatch = order.statusKind == .completed
            case .failed: bucketMatch = order.statusKind == .failed
            }
            return bucketMatch
        }
    }

    /// Symbols available in the holdings filter, sorted for stable chip order.
    var holdingsSymbols: [String] {
        positions.map(\.symbol).sorted()
    }

    init(tradingService: any TradingServiceProtocol = TradingService.shared) {
        self.tradingService = tradingService
    }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        async let ordersTask = fetchOrders()
        async let positionsTask = fetchPositions()
        do {
            let (fetchedOrders, fetchedPositions) = try await (ordersTask, positionsTask)
            // A newer load may have been kicked off (and may have already
            // finished); discard our results so we don't clobber it.
            guard !Task.isCancelled else { return }
            orders = fetchedOrders.sorted { lhs, rhs in
                switch (lhs.representativeDate, rhs.representativeDate) {
                case let (l?, r?): return l > r
                case (_?, nil): return true
                case (nil, _?): return false
                default: return false
                }
            }
            positions = fetchedPositions
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled else { return }
            self.error = error.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }

    private func fetchOrders() async throws -> [OrderResponse] {
        try await tradingService.listOrders(
            status: statusFilter.apiValue,
            side: sideFilter.apiValue,
            symbols: holdingsFilter,
            after: timeframeFilter.afterDate(),
            until: nil,
            limit: 100
        )
    }

    private func fetchPositions() async throws -> [PositionResponse] {
        try await tradingService.listPositions()
    }

    private func reloadIfNeeded<T: Equatable>(oldValue: T, newValue: T) {
        guard oldValue != newValue else { return }
        loadTask?.cancel()
        loadTask = Task { [weak self] in await self?.load() }
    }
}
