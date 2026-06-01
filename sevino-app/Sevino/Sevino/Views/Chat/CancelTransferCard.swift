import SwiftUI

/// Chat gen-UI card for a pending ACH transfer the user can cancel with a
/// hold-to-confirm gesture. Mirrors the deliberate-action UX of
/// `TradeExecutionCard` via the shared `HoldToConfirmButton`, and doubles as
/// the receipt once cancelled. The cancel action is an injected closure so the
/// view stays decoupled from any funding service; the default rejects the
/// cancellation so an unwired host fails loudly rather than faking success.
struct CancelTransferCard: View {
    @State private var viewModel: CancelTransferCardViewModel
    var scale: CGFloat = 1

    init(
        block: CancelTransferBlock,
        scale: CGFloat = 1,
        onCancel: @escaping (String) async throws -> Void = { _ in
            throw TransferCancellationError.notCancellable
        }
    ) {
        _viewModel = State(initialValue: CancelTransferCardViewModel(block: block, onCancel: onCancel))
        self.scale = scale
    }

    private var block: CancelTransferBlock { viewModel.block }

    var body: some View {
        VStack(alignment: .leading, spacing: 14 * scale) {
            CancelTransferHeader(direction: block.direction, status: viewModel.localStatus, scale: scale)
            Text(block.amount.asCurrency())
                .font(.system(size: 30 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
            CancelTransferBankRow(bankName: block.bankName, bankMask: block.bankMask, scale: scale)
            CancelTransferInitiatedLabel(initiatedAt: block.initiatedAt, scale: scale)
            CancelTransferActionZone(viewModel: viewModel, scale: scale)
                .padding(.top, 2 * scale)
        }
        .padding(16 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GenUICardBackground(cornerRadius: 20 * scale))
        .padding(.horizontal, 16 * scale)
        .animation(.spring(duration: 0.35, bounce: 0.15), value: viewModel.localStatus)
    }
}

private struct CancelTransferHeader: View {
    let direction: TransferDirection
    let status: TransferStatus
    let scale: CGFloat

    private var directionLabel: String {
        switch direction {
        case .deposit: return L10n.CancelTransfer.headerDeposit
        case .withdraw: return L10n.CancelTransfer.headerWithdrawal
        }
    }

    var body: some View {
        HStack(spacing: 8 * scale) {
            Text(directionLabel)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer(minLength: 0)
            CancelTransferStatusPill(status: status, scale: scale)
        }
    }
}

private struct CancelTransferStatusPill: View {
    let status: TransferStatus
    let scale: CGFloat

    private var text: String {
        switch status {
        case .pending: return L10n.CancelTransfer.statusPending
        case .cancelled: return L10n.CancelTransfer.statusCancelled
        case .failed: return L10n.CancelTransfer.statusFailed
        }
    }

    private var color: Color {
        switch status {
        case .pending: return .sevinoGreyContrast
        case .cancelled: return .sevinoPositive
        case .failed: return .sevinoNegative
        }
    }

    var body: some View {
        Text(text)
            .font(.system(size: 12 * scale, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 10 * scale)
            .padding(.vertical, 4 * scale)
            .background(color.opacity(0.16), in: .capsule)
    }
}

private struct CancelTransferBankRow: View {
    let bankName: String
    let bankMask: String?
    let scale: CGFloat

    private var display: String {
        if let bankMask {
            return L10n.CancelTransfer.bankAccountFormat(bankName, bankMask)
        }
        return bankName
    }

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "building.columns")
                .font(.system(size: 13 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoGreyContrast)
                .accessibilityHidden(true)
            Text(display)
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
        }
    }
}

private struct CancelTransferInitiatedLabel: View {
    let initiatedAt: Date
    let scale: CGFloat

    var body: some View {
        Text(label())
            .font(.system(size: 13 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
    }

    private func label(now: Date = .now) -> String {
        let elapsed = now.timeIntervalSince(initiatedAt)
        if elapsed >= 0, elapsed < 7 * 24 * 3600 {
            return Self.relativeFormatter.localizedString(for: initiatedAt, relativeTo: now)
        }
        return Self.absoluteFormatter.string(from: initiatedAt)
    }

    private static let relativeFormatter: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .full
        return f
    }()

    private static let absoluteFormatter: DateFormatter = {
        let f = DateFormatter()
        f.setLocalizedDateFormatFromTemplate("MMM d, h:mm a")
        return f
    }()
}

private struct CancelTransferActionZone: View {
    let viewModel: CancelTransferCardViewModel
    let scale: CGFloat

    var body: some View {
        switch viewModel.localStatus {
        case .pending:
            VStack(alignment: .leading, spacing: 8 * scale) {
                HoldToConfirmButton(
                    title: L10n.CancelTransfer.holdToCancel,
                    isEnabled: !viewModel.isCancelling,
                    scale: scale,
                    accessibilityHint: L10n.CancelTransfer.holdToCancelA11yHint,
                    action: cancel
                )
                if let error = viewModel.error {
                    Text(error)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoNegative)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        case .cancelled:
            CancelTransferStatusBanner(
                systemImage: "checkmark.circle.fill",
                text: L10n.CancelTransfer.cancelled,
                color: .sevinoPositive,
                scale: scale
            )
        case .failed:
            CancelTransferStatusBanner(
                systemImage: "exclamationmark.triangle.fill",
                text: viewModel.error ?? L10n.CancelTransfer.cancellationFailed,
                color: .sevinoNegative,
                scale: scale
            )
        }
    }

    private func cancel() {
        Task { await viewModel.cancel() }
    }
}

private struct CancelTransferStatusBanner: View {
    let systemImage: String
    let text: String
    let color: Color
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: systemImage)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(color)
                .accessibilityHidden(true)
            Text(text)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(color)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

#Preview("Pending deposit") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelTransferCard(
            block: CancelTransferBlock(
                blockId: "blk_1",
                transferId: "trf_1",
                direction: .deposit,
                amount: 500,
                bankName: "Chase",
                bankMask: "1234",
                initiatedAt: Date(timeIntervalSinceNow: -2 * 3600),
                status: .pending
            ),
            onCancel: { _ in try? await Task.sleep(for: .seconds(1)) }
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Pending withdrawal") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelTransferCard(
            block: CancelTransferBlock(
                blockId: "blk_2",
                transferId: "trf_2",
                direction: .withdraw,
                amount: 200,
                bankName: "Wells Fargo",
                bankMask: "5678",
                initiatedAt: Date(timeIntervalSinceNow: -45 * 60),
                status: .pending
            )
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Cancelled receipt") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelTransferCard(
            block: CancelTransferBlock(
                blockId: "blk_3",
                transferId: "trf_3",
                direction: .deposit,
                amount: 500,
                bankName: "Chase",
                bankMask: "1234",
                initiatedAt: Date(timeIntervalSinceNow: -3 * 3600),
                status: .cancelled
            )
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Failed (terminal)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelTransferCard(
            block: CancelTransferBlock(
                blockId: "blk_4",
                transferId: "trf_4",
                direction: .withdraw,
                amount: 1250,
                bankName: "Bank of America",
                bankMask: nil,
                initiatedAt: Date(timeIntervalSinceNow: -26 * 3600),
                status: .failed
            )
        )
    }
    .preferredColorScheme(.dark)
}
