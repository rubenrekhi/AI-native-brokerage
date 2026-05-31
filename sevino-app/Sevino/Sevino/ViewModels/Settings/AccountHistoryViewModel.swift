import Foundation

enum AccountHistoryItem: Identifiable, Equatable {
    case transfer(TransferResponse)
    case dividend(DividendResponse)

    /// Namespaced so a transfer and dividend that share a raw id can't collide
    /// when SwiftUI keys the merged `ForEach`.
    var id: String {
        switch self {
        case .transfer(let t): return "t-\(t.id)"
        case .dividend(let d): return "d-\(d.id)"
        }
    }

    var sortDate: Date? {
        switch self {
        case .transfer(let t): return t.createdAtDate
        case .dividend(let d): return d.createdAtDate
        }
    }
}

enum AccountHistoryTypeFilter: Hashable, CaseIterable, Identifiable {
    case all, deposits, withdrawals, dividends
    var id: Self { self }
}

enum AccountHistoryTimeframeFilter: Hashable, CaseIterable, Identifiable {
    case all, last7Days, last30Days, last90Days
    var id: Self { self }

    func afterDate(now: Date = .now) -> Date? {
        let calendar = Calendar(identifier: .gregorian)
        switch self {
        case .all: return nil
        case .last7Days: return calendar.date(byAdding: .day, value: -7, to: now)
        case .last30Days: return calendar.date(byAdding: .day, value: -30, to: now)
        case .last90Days: return calendar.date(byAdding: .day, value: -90, to: now)
        }
    }
}

@Observable
final class AccountHistoryViewModel {
    private let fundingService: any FundingServiceProtocol
    private let now: () -> Date

    private(set) var items: [AccountHistoryItem] = []
    private(set) var isLoading = false
    private(set) var error: String?

    var typeFilter: AccountHistoryTypeFilter = .all
    var timeframeFilter: AccountHistoryTimeframeFilter = .all

    var visibleItems: [AccountHistoryItem] {
        let after = timeframeFilter.afterDate(now: now())
        return items.filter { item in
            matchesType(item) && matchesTimeframe(item, after: after)
        }
    }

    /// Bindable flag the view alerts on. Only true when we have cached
    /// items to fall back to — a first-load failure renders inline via
    /// `errorState` instead of an alert.
    var isShowingError: Bool {
        get { error != nil && !items.isEmpty }
        set { if !newValue { clearError() } }
    }

    init(
        fundingService: any FundingServiceProtocol = FundingService.shared,
        now: @escaping () -> Date = Date.init
    ) {
        self.fundingService = fundingService
        self.now = now
    }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            async let transfersTask = fundingService.listTransfers()
            async let dividendsTask = fundingService.listDividends(limit: 50, offset: 0)
            let (transfers, dividends) = try await (transfersTask, dividendsTask)

            let merged: [AccountHistoryItem] =
                transfers.map(AccountHistoryItem.transfer)
                + dividends.map(AccountHistoryItem.dividend)

            items = merged.sorted { lhs, rhs in
                switch (lhs.sortDate, rhs.sortDate) {
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

    private func matchesType(_ item: AccountHistoryItem) -> Bool {
        switch (typeFilter, item) {
        case (.all, _):
            return true
        case (.deposits, .transfer(let t)):
            return TransferDirection(apiValue: t.direction) == .deposit
        case (.withdrawals, .transfer(let t)):
            return TransferDirection(apiValue: t.direction) == .withdraw
        case (.dividends, .dividend):
            return true
        default:
            return false
        }
    }

    private func matchesTimeframe(_ item: AccountHistoryItem, after: Date?) -> Bool {
        guard let after else { return true }
        guard let date = item.sortDate else { return false }
        return date >= after
    }
}
