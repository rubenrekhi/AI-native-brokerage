import SwiftUI

/// Chat gen-UI card for cancelling a pending order via a hold-to-confirm
/// gesture. On a completed hold it transitions to a "Cancelled" receipt; a
/// thrown error drives it to a failed state — retryable for transient errors,
/// terminal for broker rejections. Frontend-only: the cancel action is
/// injected, defaulting to a no-op so the dispatcher can render the card before
/// the backend tool lands.
struct CancelOrderCard: View {
    @State private var viewModel: CancelOrderCardViewModel
    let scale: CGFloat

    init(
        block: CancelOrderBlock,
        scale: CGFloat = 1,
        onCancel: @escaping (String) async throws -> Void = { _ in }
    ) {
        _viewModel = State(initialValue: CancelOrderCardViewModel(block: block, onCancel: onCancel))
        self.scale = scale
    }

    private var block: CancelOrderBlock { viewModel.block }

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            VStack(alignment: .leading, spacing: 16 * scale) {
                header
                assetRow
                detailBlock
                footer
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(accessibilitySummary)

            actionZone
        }
        .padding(20 * scale)
        .background(GenUICardBackground(cornerRadius: 24 * scale))
        .padding(.horizontal, 16 * scale)
        .animation(.spring(duration: 0.35, bounce: 0.15), value: viewModel.localStatus)
    }

    private var header: some View {
        HStack(spacing: 8 * scale) {
            Text(headerSideLabel)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer(minLength: 0)
            statusPill
        }
    }

    private var statusPill: some View {
        let (label, color): (String, Color) = switch viewModel.localStatus {
        case .pending: (L10n.CancelOrder.statusPending, .sevinoGreyContrast)
        case .cancelled: (L10n.CancelOrder.statusCancelled, .sevinoPositive)
        case .failed: (L10n.CancelOrder.statusFailed, .sevinoNegative)
        }
        return Text(label)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8 * scale)
            .padding(.vertical, 3 * scale)
            .background(Capsule().fill(color.opacity(0.15)))
    }

    private var assetRow: some View {
        HStack(spacing: 12 * scale) {
            StockLogoView(ticker: block.symbol, size: 40 * scale)
            VStack(alignment: .leading, spacing: 2 * scale) {
                Text(block.symbol)
                    .font(.body.weight(.bold))
                    .foregroundStyle(Color.sevinoSecondary)
                if let companyName = block.companyName {
                    Text(companyName)
                        .font(.subheadline)
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
            sideBadge
        }
    }

    private var sideBadge: some View {
        let isSell = block.side == .sell
        let color: Color = isSell ? .sevinoNegative : .sevinoPositive
        let label = isSell ? L10n.CancelOrder.sideSell : L10n.CancelOrder.sideBuy
        return Text(label)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 4 * scale)
            .background(RoundedRectangle(cornerRadius: 8 * scale).fill(color.opacity(0.18)))
    }

    private var detailBlock: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(detailText)
                .font(.body.weight(.semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let partialFillNote {
                Text(partialFillNote)
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var detailText: String {
        let qty = block.qty.map { $0.asShareCount() }
        switch block.orderType {
        case .market:
            if let qty {
                return L10n.CancelOrder.sharesAtMarket(qty)
            }
            if let notional = block.notional {
                return L10n.CancelOrder.notionalMarket(notional.asCurrency())
            }
            return ""
        case .limit:
            if let qty, let limitPrice = block.limitPrice {
                return L10n.CancelOrder.sharesAtLimit(qty, limitPrice.asCurrency())
            }
            return ""
        }
    }

    /// "3/10 filled — cancelling the rest", shown while the order is still
    /// live (pending/failed). The cancelled receipt reports the filled count
    /// separately, so suppress it there.
    private var partialFillNote: String? {
        guard viewModel.localStatus != .cancelled,
              block.filledQty > 0,
              let qty = block.qty else { return nil }
        return L10n.CancelOrder.partialFillNote(block.filledQty.asShareCount(), qty.asShareCount())
    }

    private var footer: some View {
        Text(L10n.CancelOrder.footerFormat(timeInForceLabel, relativeSubmittedAt))
            .font(.footnote)
            .foregroundStyle(Color.sevinoGreyContrast)
    }

    private var timeInForceLabel: String {
        switch block.timeInForce.lowercased() {
        case "day": L10n.CancelOrder.dayOrder
        case "gtc": L10n.CancelOrder.gtcOrder
        default: block.timeInForce.uppercased()
        }
    }

    private var relativeSubmittedAt: String {
        Self.relativeFormatter.localizedString(for: block.submittedAt, relativeTo: .now)
    }

    private static let relativeFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter
    }()

    private func performCancel() {
        Task { await viewModel.cancel() }
    }

    private var cancelButton: some View {
        HoldToConfirmButton(
            title: L10n.CancelOrder.holdToCancel,
            isEnabled: !viewModel.isCancelling,
            scale: scale,
            accessibilityHint: L10n.CancelOrder.holdToCancelA11yHint,
            action: performCancel
        )
    }

    @ViewBuilder
    private var actionZone: some View {
        switch viewModel.localStatus {
        case .pending:
            cancelButton
        case .cancelled:
            VStack(spacing: 8 * scale) {
                TradeStatusBanner(
                    text: L10n.CancelOrder.statusCancelled,
                    systemImage: "checkmark",
                    color: .sevinoPositive,
                    scale: scale
                )
                if block.filledQty > 0 {
                    Text(L10n.CancelOrder.filledShares(block.filledQty.asShareCount()))
                        .font(.footnote)
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
        case .failed:
            VStack(spacing: 8 * scale) {
                TradeStatusBanner(
                    text: viewModel.error ?? L10n.CancelOrder.cancellationFailed,
                    systemImage: "exclamationmark.triangle.fill",
                    color: .sevinoNegative,
                    scale: scale
                )
                if viewModel.isRetryable {
                    cancelButton
                }
            }
        }
    }

    private var headerSideLabel: String {
        block.side == .sell ? L10n.CancelOrder.headerPendingSell : L10n.CancelOrder.headerPendingBuy
    }

    private var accessibilitySummary: String {
        var parts = [headerSideLabel, block.companyName ?? block.symbol, detailText]
        if let partialFillNote { parts.append(partialFillNote) }
        parts.append(L10n.CancelOrder.footerFormat(timeInForceLabel, relativeSubmittedAt))
        return parts.filter { !$0.isEmpty }.joined(separator: ", ")
    }
}

private func previewBlock(
    orderId: String = "ord_1",
    symbol: String = "AAPL",
    companyName: String? = "Apple Inc.",
    side: OrderSide = .buy,
    orderType: OrderType = .market,
    qty: Decimal? = 10,
    notional: Decimal? = nil,
    limitPrice: Decimal? = nil,
    filledQty: Decimal = 0,
    timeInForce: String = "day",
    minutesAgo: Double = 120,
    status: OrderCancellationStatus = .pending
) -> CancelOrderBlock {
    CancelOrderBlock(
        blockId: "blk_\(orderId)",
        orderId: orderId,
        symbol: symbol,
        companyName: companyName,
        side: side,
        orderType: orderType,
        qty: qty,
        notional: notional,
        limitPrice: limitPrice,
        filledQty: filledQty,
        timeInForce: timeInForce,
        submittedAt: Date(timeIntervalSinceNow: -minutesAgo * 60),
        status: status
    )
}

#Preview("Pending market buy") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelOrderCard(block: previewBlock())
    }
}

#Preview("Pending market buy (notional)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelOrderCard(block: previewBlock(qty: nil, notional: 500))
    }
}

#Preview("Pending limit sell (GTC)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelOrderCard(
            block: previewBlock(
                symbol: "TSLA",
                companyName: "Tesla, Inc.",
                side: .sell,
                orderType: .limit,
                qty: 5,
                limitPrice: 250,
                timeInForce: "gtc"
            )
        )
    }
}

#Preview("Pending limit buy (partial fill)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelOrderCard(
            block: previewBlock(orderType: .limit, qty: 10, limitPrice: 190, filledQty: 3)
        )
    }
}

#Preview("Cancelled (receipt, partial fill)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelOrderCard(
            block: previewBlock(orderType: .limit, qty: 10, limitPrice: 190, filledQty: 3, status: .cancelled)
        )
    }
}

#Preview("Failed (retry)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CancelOrderCard(block: previewBlock(status: .failed))
    }
}
