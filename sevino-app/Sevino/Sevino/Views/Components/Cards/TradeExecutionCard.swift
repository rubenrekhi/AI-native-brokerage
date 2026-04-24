import SwiftUI

/// Visual state of a `TradeExecutionCard`. Owned by the parent — the card itself is pure.
enum TradeExecutionState: Equatable, Hashable {
    case pending
    case success
    case error(String)
}

/// MCP chat card that previews a pending trade and lets the user confirm it with a long press.
///
/// Pure presentation — the parent owns `state` and transitions it from `.pending` to `.success`
/// or `.error(message)` after `onConfirm` runs. When `onConfirm` is `nil` the card renders as
/// a read-only order receipt with no hold-to-confirm button.
///
/// The parent is responsible for:
/// 1. Transitioning `state` to `.success` after `onConfirm` returns normally.
/// 2. Transitioning `state` to `.error(message)` if `onConfirm` throws or the order fails.
/// 3. Owning the `Task` that drives `onConfirm` so it can be cancelled on teardown.
struct TradeExecutionCard: View {
    let data: TradeExecutionCardData
    let state: TradeExecutionState
    var scale: CGFloat = 1
    var onConfirm: (() async -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 20 * scale) {
            TradeSideBadge(side: data.side, scale: scale)
            TradeStockInfo(data: data, scale: scale)
            TradeOrderDetails(data: data, scale: scale)
            Divider()
            TradeEstimatedTotalRow(estimatedTotal: data.estimatedTotal)
            TradeFooterAction(state: state, scale: scale, onConfirm: onConfirm)
            TradeDisclaimer(text: data.disclaimer)
        }
        .padding(20 * scale)
        .background(
            RoundedRectangle(cornerRadius: 24 * scale)
                .fill(Color.sevinoSettingsContrast)
        )
        .animation(.spring(duration: 0.35, bounce: 0.15), value: state)
    }
}

private struct TradeSideBadge: View {
    let side: TradeSide
    let scale: CGFloat

    private var color: Color { side == .buy ? .sevinoInfo : .sevinoNegative }
    private var label: String { side == .buy ? L10n.TradeExecution.sideBuy : L10n.TradeExecution.sideSell }

    var body: some View {
        Text(label)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 4 * scale)
            .background(
                RoundedRectangle(cornerRadius: 8 * scale)
                    .fill(color.opacity(0.18))
            )
    }
}

private struct TradeStockInfo: View {
    let data: TradeExecutionCardData
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 12 * scale) {
            StockLogoView(ticker: data.ticker, size: 40 * scale)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2 * scale) {
                Text(data.companyName)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(L10n.TradeExecution.tickerExchangeFormat(data.ticker, data.exchange))
                    .font(.subheadline)
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
    }
}

private struct TradeOrderDetails: View {
    let data: TradeExecutionCardData
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 0) {
            TradeDetailRow(label: L10n.TradeExecution.labelOrderType, value: data.orderType, scale: scale)
            Divider()
            TradeDetailRow(label: L10n.TradeExecution.labelAmount, value: data.amount, scale: scale)
            Divider()
            TradeDetailRow(label: L10n.TradeExecution.labelEstimatedShares, value: data.estimatedShares, scale: scale)
            Divider()
            TradeDetailRow(label: L10n.TradeExecution.labelCurrentPrice, value: data.currentPrice, scale: scale)
        }
    }
}

private struct TradeDetailRow: View {
    let label: String
    let value: String
    let scale: CGFloat

    var body: some View {
        HStack {
            Text(label)
                .font(.body)
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer()
            Text(value)
                .font(.body.weight(.semibold))
                .foregroundStyle(Color.sevinoSecondary)
        }
        .padding(.vertical, 10 * scale)
    }
}

private struct TradeEstimatedTotalRow: View {
    let estimatedTotal: String

    var body: some View {
        HStack {
            Text(L10n.TradeExecution.labelEstimatedTotal)
                .font(.body)
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer()
            Text(estimatedTotal)
                .font(.title2.weight(.bold))
                .foregroundStyle(Color.sevinoPositive)
        }
    }
}

private struct TradeFooterAction: View {
    let state: TradeExecutionState
    let scale: CGFloat
    let onConfirm: (() async -> Void)?

    var body: some View {
        switch state {
        case .pending:
            if let onConfirm {
                HoldToConfirmButton(title: L10n.TradeExecution.holdToConfirm, scale: scale) {
                    Task { await onConfirm() }
                }
            }
        case .success:
            TradeStatusBanner(
                text: L10n.TradeExecution.orderSubmitted,
                systemImage: "checkmark",
                color: .sevinoPositive,
                scale: scale
            )
        case .error(let message):
            TradeStatusBanner(
                text: message.isEmpty ? L10n.TradeExecution.errorSubmittingOrder : message,
                systemImage: nil,
                color: .sevinoNegative,
                scale: scale
            )
        }
    }
}

private struct TradeDisclaimer: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(Color.sevinoGreyContrast)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private let tradeExecutionPreviewData = TradeExecutionCardData(
    side: .buy,
    ticker: "AMD",
    companyName: "Advanced Micro Devices inc.",
    exchange: "NYSE",
    orderType: "Market Order",
    amount: "$500.00",
    estimatedShares: "1.82",
    currentPrice: "$274.63",
    estimatedTotal: "$500.00",
    disclaimer: "Market orders execute at the best available price at market open"
)

#Preview("Pending (buy)") {
    TradeExecutionCard(
        data: tradeExecutionPreviewData,
        state: .pending,
        onConfirm: { try? await Task.sleep(for: .seconds(1)) }
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Pending (sell)") {
    TradeExecutionCard(
        data: TradeExecutionCardData(
            side: .sell,
            ticker: "AMD",
            companyName: "Advanced Micro Devices inc.",
            exchange: "NYSE",
            orderType: "Market Order",
            amount: "$500.00",
            estimatedShares: "1.82",
            currentPrice: "$274.63",
            estimatedTotal: "$500.00",
            disclaimer: "Market orders execute at the best available price at market open"
        ),
        state: .pending,
        onConfirm: {}
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Success") {
    TradeExecutionCard(
        data: tradeExecutionPreviewData,
        state: .success,
        onConfirm: {}
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Error") {
    TradeExecutionCard(
        data: tradeExecutionPreviewData,
        state: .error("Error submitting order"),
        onConfirm: {}
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Read-only (no onConfirm)") {
    TradeExecutionCard(
        data: tradeExecutionPreviewData,
        state: .pending,
        onConfirm: nil
    )
    .padding()
    .background(Color.sevinoPrimary)
}
