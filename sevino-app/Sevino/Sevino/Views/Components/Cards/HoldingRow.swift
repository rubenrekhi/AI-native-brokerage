import SwiftUI

struct HoldingRow: View {
    let holding: Holding
    let scale: CGFloat
    @State private var isDetailExpanded = false

    private var hasDetails: Bool { holding.daysGain != nil }

    var body: some View {
        VStack(spacing: 0) {
            mainRow
            if isDetailExpanded, hasDetails {
                detailSection
            }
        }
        .clipped()
    }

    private var mainRow: some View {
        Button(action: toggleDetails) {
            HStack(spacing: 10 * scale) {
                holdingIcon
                tickerInfo
                Spacer()
                valueInfo

                if hasDetails {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .rotationEffect(.degrees(isDetailExpanded ? -180 : 0))
                        .accessibilityHidden(true)
                }
            }
            .padding(.vertical, 8 * scale)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(!hasDetails)
    }

    private var holdingIcon: some View {
        Group {
            if holding.isCash {
                Image(systemName: "dollarsign.circle.fill")
                    .font(.system(size: 28 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 36 * scale, height: 36 * scale)
            } else {
                StockLogoView(ticker: holding.ticker, size: 28 * scale)
            }
        }
    }

    private var tickerInfo: some View {
        VStack(alignment: .leading, spacing: 2 * scale) {
            Text(holding.ticker)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            if let shares = holding.shares {
                Text(L10n.Home.holdingsShares(shares))
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }

    private var valueInfo: some View {
        VStack(alignment: .trailing, spacing: 2 * scale) {
            Text(holding.value)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            if let gainLoss = holding.gainLossText, let isPositive = holding.isPositive {
                Text(gainLoss)
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(isPositive ? Color.sevinoPositive : Color.sevinoNegative)
            }
        }
    }

    private var detailSection: some View {
        VStack(spacing: 0) {
            Text(L10n.Home.holdingsMyHoldings)
                .font(.system(size: 15 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, 8 * scale)

            if let daysGain = holding.daysGain, let daysPercent = holding.daysGainPercent {
                detailRow(
                    label: L10n.Home.holdingsDaysGain,
                    value: "\(daysGain) (\(daysPercent))",
                    isPositive: holding.isPositive
                )
            }

            if let totalGain = holding.totalGain, let totalPercent = holding.totalGainPercent {
                detailRow(
                    label: L10n.Home.holdingsTotalGain,
                    value: "\(totalGain) (\(totalPercent))",
                    isPositive: holding.isPositive
                )
            }

            if let avgCost = holding.averageCost {
                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(L10n.Home.holdingsAverageCost)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Text(avgCost)
                        .font(.system(size: 18 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 8 * scale)
            }
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
        .padding(.top, 8 * scale)
        .transition(.opacity)
    }

    private func detailRow(label: String, value: String, isPositive: Bool?) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer()
            Text(value)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(isPositive == true ? Color.sevinoPositive : Color.sevinoNegative)
        }
        .padding(.vertical, 6 * scale)
    }

    private func toggleDetails() {
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            isDetailExpanded.toggle()
        }
    }
}
