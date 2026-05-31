import SwiftUI

struct AccountHistoryView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: AccountHistoryViewModel
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    init(vm: AccountHistoryViewModel = AccountHistoryViewModel()) {
        _vm = State(initialValue: vm)
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                SettingsHeaderView(title: L10n.Settings.accountHistory, scale: scale, onBack: { dismiss() })
                    .padding(.bottom, 16 * scale)

                filterBar
                    .padding(.bottom, 16 * scale)

                content
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .navigationBarBackButtonHidden()
        .task { await vm.load() }
        .alert(
            L10n.Settings.accountHistoryErrorTitle,
            isPresented: Bindable(vm).isShowingError,
            presenting: vm.error
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: vm.clearError)
        } message: { message in
            Text(message)
        }
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.items.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.error, vm.items.isEmpty {
            errorState(message: error)
        } else if vm.items.isEmpty {
            emptyState
        } else {
            list
        }
    }

    private var filterBar: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8 * scale) {
                FilterMenu(
                    label: L10n.Settings.accountHistoryFilterTypeLabel,
                    selectionLabel: typeLabel(vm.typeFilter),
                    isActive: vm.typeFilter != .all,
                    scale: scale
                ) {
                    Picker("", selection: Bindable(vm).typeFilter) {
                        Text(L10n.Settings.accountHistoryFilterAll).tag(AccountHistoryTypeFilter.all)
                        Text(L10n.Settings.accountHistoryFilterDeposits).tag(AccountHistoryTypeFilter.deposits)
                        Text(L10n.Settings.accountHistoryFilterWithdrawals).tag(AccountHistoryTypeFilter.withdrawals)
                        Text(L10n.Settings.accountHistoryFilterDividends).tag(AccountHistoryTypeFilter.dividends)
                    }
                }

                FilterMenu(
                    label: L10n.Settings.accountHistoryFilterTimeframeLabel,
                    selectionLabel: timeframeLabel(vm.timeframeFilter),
                    isActive: vm.timeframeFilter != .all,
                    scale: scale
                ) {
                    Picker("", selection: Bindable(vm).timeframeFilter) {
                        Text(L10n.Settings.accountHistoryFilterAll).tag(AccountHistoryTimeframeFilter.all)
                        Text(L10n.Settings.accountHistoryFilter7d).tag(AccountHistoryTimeframeFilter.last7Days)
                        Text(L10n.Settings.accountHistoryFilter30d).tag(AccountHistoryTimeframeFilter.last30Days)
                        Text(L10n.Settings.accountHistoryFilter90d).tag(AccountHistoryTimeframeFilter.last90Days)
                    }
                }
            }
        }
        .scrollIndicators(.hidden)
    }

    @ViewBuilder
    private var list: some View {
        let visible = vm.visibleItems
        if visible.isEmpty {
            filteredEmptyState
        } else {
            ScrollView {
                LazyVStack(spacing: 12 * scale) {
                    ForEach(visible) { item in
                        switch item {
                        case .transfer(let transfer):
                            AccountHistoryRow(transfer: transfer, scale: scale)
                        case .dividend(let dividend):
                            DividendHistoryRow(dividend: dividend, scale: scale)
                        }
                    }
                }
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)
            .refreshable { await vm.load() }
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(L10n.Settings.accountHistoryEmptyTitle, systemImage: "arrow.left.arrow.right.circle")
        } description: {
            Text(L10n.Settings.accountHistoryEmptyMessage)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var filteredEmptyState: some View {
        ContentUnavailableView {
            Label(L10n.Settings.accountHistoryFilteredEmptyTitle, systemImage: "line.3.horizontal.decrease.circle")
        } description: {
            Text(L10n.Settings.accountHistoryFilteredEmptyMessage)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func typeLabel(_ filter: AccountHistoryTypeFilter) -> String {
        switch filter {
        case .all: L10n.Settings.accountHistoryFilterAll
        case .deposits: L10n.Settings.accountHistoryFilterDeposits
        case .withdrawals: L10n.Settings.accountHistoryFilterWithdrawals
        case .dividends: L10n.Settings.accountHistoryFilterDividends
        }
    }

    private func timeframeLabel(_ filter: AccountHistoryTimeframeFilter) -> String {
        switch filter {
        case .all: L10n.Settings.accountHistoryFilterAll
        case .last7Days: L10n.Settings.accountHistoryFilter7d
        case .last30Days: L10n.Settings.accountHistoryFilter30d
        case .last90Days: L10n.Settings.accountHistoryFilter90d
        }
    }

    private func errorState(message: String) -> some View {
        VStack(spacing: 12 * scale) {
            Text(message)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoNegative)
                .multilineTextAlignment(.center)

            Button(L10n.General.tryAgain, action: retry)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(minWidth: 44, minHeight: 44)
                .padding(.horizontal, 16 * scale)
                .contentShape(Rectangle())
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.vertical, 16 * scale)
    }

    private func retry() {
        Task { await vm.load() }
    }
}

private struct AccountHistoryRow: View {
    let transfer: TransferResponse
    let scale: CGFloat

    private enum Kind { case deposit, withdraw, unknown }

    private var kind: Kind {
        switch TransferDirection(apiValue: transfer.direction) {
        case .deposit: .deposit
        case .withdraw: .withdraw
        case nil: .unknown
        }
    }

    private var statusKind: TransferStatusKind {
        TransferStatusKind.from(transfer.status)
    }

    private var bankTitle: String {
        if let nickname = transfer.bank?.nickname, !nickname.isEmpty { return nickname }
        if let name = transfer.bank?.institutionName, !name.isEmpty { return name }
        return L10n.Settings.accountHistoryUnknownBank
    }

    private var bankSubtitle: String? {
        guard let mask = transfer.bank?.accountMask, !mask.isEmpty else { return nil }
        return "•••• \(mask)"
    }

    private var directionLabel: String {
        switch kind {
        case .deposit: L10n.Settings.accountHistoryDepositLabel
        case .withdraw: L10n.Settings.accountHistoryWithdrawalLabel
        case .unknown: L10n.Transfer.statusUnknown
        }
    }

    private var directionGlyph: String {
        switch kind {
        case .deposit: "arrow.down"
        case .withdraw: "arrow.up"
        case .unknown: "arrow.left.arrow.right"
        }
    }

    private var amountColor: Color {
        switch kind {
        case .deposit: Color.sevinoPositive
        case .withdraw, .unknown: Color.sevinoSecondary
        }
    }

    private var amountPrefix: String {
        switch kind {
        case .deposit: "+"
        case .withdraw: "−"
        case .unknown: ""
        }
    }

    private var amountText: String {
        let formatted = transfer.amountValue.formatted(.currency(code: "USD"))
        return "\(amountPrefix)\(formatted)"
    }

    private var dateText: String {
        guard let date = transfer.createdAtDate else { return "" }
        return date.formatted(.dateTime.month(.abbreviated).day().year())
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12 * scale) {
            Image(systemName: directionGlyph)
                .font(.system(size: 14 * scale, weight: .bold))
                .foregroundStyle(amountColor)
                .frame(width: 36 * scale, height: 36 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.2), in: .circle)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4 * scale) {
                HStack(spacing: 6 * scale) {
                    Text(directionLabel)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)

                    StatusBadge(kind: statusKind, scale: scale)
                }

                Text(bankTitle)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .lineLimit(1)

                if let subtitle = bankSubtitle {
                    Text(subtitle)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }

            Spacer(minLength: 0)

            VStack(alignment: .trailing, spacing: 4 * scale) {
                Text(amountText)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(amountColor)

                if !dateText.isEmpty {
                    Text(dateText)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
        }
        .padding(14 * scale)
        .modifier(SevinoGlass.card)
    }
}

private struct DividendHistoryRow: View {
    let dividend: DividendResponse
    let scale: CGFloat

    private var statusKind: DividendStatusKind {
        DividendStatusKind.from(dividend.status)
    }

    private var statusLabel: String {
        switch statusKind {
        case .settled: L10n.Dividend.statusSettled
        case .pending: L10n.Dividend.statusPending
        case .failed: L10n.Dividend.statusFailed
        case .unknown: L10n.Dividend.statusUnknown
        }
    }

    private var amountText: String {
        let formatted = dividend.netAmountValue.formatted(.currency(code: "USD"))
        return "+\(formatted)"
    }

    private var dateText: String {
        guard let date = dividend.createdAtDate else { return "" }
        return date.formatted(.dateTime.month(.abbreviated).day().year())
    }

    private var accessibilityLabel: String {
        var parts: [String] = [
            L10n.Settings.accountHistoryDividendLabel,
            dividend.symbol,
            amountText,
            statusLabel,
        ]
        if !dateText.isEmpty { parts.append(dateText) }
        return parts.joined(separator: ", ")
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12 * scale) {
            Image(systemName: "dollarsign.circle")
                .font(.system(size: 14 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoPositive)
                .frame(width: 36 * scale, height: 36 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.2), in: .circle)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4 * scale) {
                HStack(spacing: 6 * scale) {
                    Text(L10n.Settings.accountHistoryDividendLabel)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)

                    DividendStatusBadge(kind: statusKind, scale: scale)
                }

                Text(dividend.symbol)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .lineLimit(1)
            }

            Spacer(minLength: 0)

            VStack(alignment: .trailing, spacing: 4 * scale) {
                Text(amountText)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoPositive)

                if !dateText.isEmpty {
                    Text(dateText)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
        }
        .padding(14 * scale)
        .modifier(SevinoGlass.card)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
    }
}

private struct StatusBadge: View {
    let kind: TransferStatusKind
    let scale: CGFloat

    private var label: String {
        switch kind {
        case .queued: L10n.Transfer.statusQueued
        case .complete: L10n.Transfer.statusComplete
        case .failed: L10n.Transfer.statusFailed
        case .unknown: L10n.Transfer.statusUnknown
        }
    }

    private var color: Color {
        switch kind {
        case .queued, .unknown: Color.sevinoWarning
        case .complete: Color.sevinoPositive
        case .failed: Color.sevinoNegative
        }
    }

    var body: some View {
        Text(label)
            .font(.system(size: 10 * scale, weight: .semibold))
            .tracking(0.5)
            .foregroundStyle(color)
            .padding(.horizontal, 8 * scale)
            .padding(.vertical, 3 * scale)
            .background(color.opacity(0.15), in: .capsule)
    }
}

private struct DividendStatusBadge: View {
    let kind: DividendStatusKind
    let scale: CGFloat

    private var label: String {
        switch kind {
        case .settled: L10n.Dividend.statusSettled
        case .pending: L10n.Dividend.statusPending
        case .failed: L10n.Dividend.statusFailed
        case .unknown: L10n.Dividend.statusUnknown
        }
    }

    private var color: Color {
        switch kind {
        case .pending, .unknown: Color.sevinoWarning
        case .settled: Color.sevinoPositive
        case .failed: Color.sevinoNegative
        }
    }

    var body: some View {
        Text(label)
            .font(.system(size: 10 * scale, weight: .semibold))
            .tracking(0.5)
            .foregroundStyle(color)
            .padding(.horizontal, 8 * scale)
            .padding(.vertical, 3 * scale)
            .background(color.opacity(0.15), in: .capsule)
    }
}

#if DEBUG
#Preview("Loaded — all filters have content") {
    NavigationStack {
        AccountHistoryView(vm: AccountHistoryViewModel(
            fundingService: PreviewAccountHistoryFundingService()
        ))
    }
    .preferredColorScheme(.dark)
}

#Preview("Transfers only — try Dividends or 7d filter") {
    NavigationStack {
        AccountHistoryView(vm: AccountHistoryViewModel(
            fundingService: PreviewAccountHistoryFundingService(dividends: [])
        ))
    }
    .preferredColorScheme(.dark)
}

#Preview("Dividends only — try Deposits or 7d filter") {
    NavigationStack {
        AccountHistoryView(vm: AccountHistoryViewModel(
            fundingService: PreviewAccountHistoryFundingService(transfers: [])
        ))
    }
    .preferredColorScheme(.dark)
}

#Preview("Empty — no activity yet") {
    NavigationStack {
        AccountHistoryView(vm: AccountHistoryViewModel(fundingService: PreviewNoopFundingService()))
    }
    .preferredColorScheme(.dark)
}

private final class PreviewAccountHistoryFundingService: FundingServiceProtocol, @unchecked Sendable {
    static let sampleTransfers: [TransferResponse] = [
        TransferResponse(
            id: "t-1",
            status: "COMPLETE",
            amount: "1250.00",
            direction: "INCOMING",
            createdAt: "2026-04-18T14:21:00Z",
            reason: nil,
            bank: TransferBank(nickname: nil, accountMask: "4821", institutionName: "Chase")
        ),
        TransferResponse(
            id: "t-2",
            status: "QUEUED",
            amount: "300.00",
            direction: "OUTGOING",
            createdAt: "2026-04-14T09:05:00Z",
            reason: nil,
            bank: TransferBank(nickname: "Savings", accountMask: "7733", institutionName: "Ally")
        ),
        TransferResponse(
            id: "t-3",
            status: "FAILED",
            amount: "75.00",
            direction: "INCOMING",
            createdAt: "2026-04-02T16:10:00Z",
            reason: "Insufficient funds",
            bank: TransferBank(nickname: nil, accountMask: "9102", institutionName: "Schwab Bank")
        ),
    ]

    static let sampleDividends: [DividendResponse] = [
        DividendResponse(
            id: "d-1",
            symbol: "AAPL",
            netAmount: "22.50",
            status: "executed",
            createdAt: "2026-05-28T13:30:00Z"
        ),
        DividendResponse(
            id: "d-2",
            symbol: "MSFT",
            netAmount: "8.75",
            status: "executed",
            createdAt: "2026-04-22T13:30:00Z"
        ),
        DividendResponse(
            id: "d-3",
            symbol: "KO",
            netAmount: "1.84",
            status: "correct",
            createdAt: "2026-04-10T13:30:00Z"
        ),
    ]

    private let transfersFixture: [TransferResponse]
    private let dividendsFixture: [DividendResponse]

    init(
        transfers: [TransferResponse] = PreviewAccountHistoryFundingService.sampleTransfers,
        dividends: [DividendResponse] = PreviewAccountHistoryFundingService.sampleDividends
    ) {
        self.transfersFixture = transfers
        self.dividendsFixture = dividends
    }

    func createLinkToken() async throws -> String { "" }
    func linkBank(_: LinkBankRequest) async throws -> AchRelationshipDTO { throw PreviewUnimplemented() }
    func listAchRelationships() async throws -> [AchRelationshipDTO] { [] }
    func deleteAchRelationship(id _: UUID) async throws {}
    func createReauthLinkToken(relationshipId _: UUID) async throws -> String { "" }
    func completeReauth(relationshipId _: UUID) async throws {}
    func createTransfer(
        relationshipId _: String,
        amount _: Decimal,
        direction _: TransferDirection
    ) async throws -> TransferResponse { throw PreviewUnimplemented() }

    func listTransfers() async throws -> [TransferResponse] { transfersFixture }
    func listDividends(limit _: Int, offset _: Int) async throws -> [DividendResponse] { dividendsFixture }
    func getCashInterest() async throws -> CashInterestResponse { throw PreviewUnimplemented() }
}
#endif
