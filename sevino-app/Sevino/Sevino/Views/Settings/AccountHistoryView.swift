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
                    .padding(.bottom, 24 * scale)

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
        if vm.isLoading && vm.transfers.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.error, vm.transfers.isEmpty {
            errorState(message: error)
        } else if vm.transfers.isEmpty {
            emptyState
        } else {
            transferList
        }
    }

    private var transferList: some View {
        ScrollView {
            VStack(spacing: 12 * scale) {
                ForEach(vm.transfers) { transfer in
                    AccountHistoryRow(transfer: transfer, scale: scale)
                }
            }
            .padding(.bottom, 16 * scale)
        }
        .scrollIndicators(.hidden)
        .refreshable { await vm.load() }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(L10n.Settings.accountHistoryEmptyTitle, systemImage: "arrow.left.arrow.right.circle")
        } description: {
            Text(L10n.Settings.accountHistoryEmptyMessage)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
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

#if DEBUG
#Preview("Loaded") {
    NavigationStack {
        AccountHistoryView(vm: .previewLoaded())
    }
    .preferredColorScheme(.dark)
}

#Preview("Empty") {
    NavigationStack {
        AccountHistoryView(vm: AccountHistoryViewModel(fundingService: PreviewNoopFundingService()))
    }
    .preferredColorScheme(.dark)
}

private extension AccountHistoryViewModel {
    static func previewLoaded() -> AccountHistoryViewModel {
        AccountHistoryViewModel(fundingService: PreviewAccountHistoryFundingService())
    }
}

private final class PreviewAccountHistoryFundingService: FundingServiceProtocol, @unchecked Sendable {
    func createLinkToken() async throws -> String { "" }
    func linkBank(_: LinkBankRequest) async throws -> AchRelationshipDTO { throw PreviewUnimplemented() }
    func listAchRelationships() async throws -> [AchRelationshipDTO] { [] }
    func deleteAchRelationship(id _: UUID) async throws {}
    func createTransfer(
        relationshipId _: String,
        amount _: Decimal,
        direction _: TransferDirection
    ) async throws -> TransferResponse { throw PreviewUnimplemented() }

    func listTransfers() async throws -> [TransferResponse] {
        [
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
    }

    func getCashInterest() async throws -> CashInterestResponse {
        throw PreviewUnimplemented()
    }
}
#endif
