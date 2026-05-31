import SwiftUI

struct HoldingRow: View {
    let holding: Holding
    let scale: CGFloat
    let isExpanded: Bool
    let onToggle: () -> Void

    private var hasDetails: Bool { !holding.isCash }

    var body: some View {
        VStack(spacing: 0) {
            mainRow
            if isExpanded, hasDetails {
                detailSection
            }
            // Auto-scroll target. VStack realizes a zero-height view, so
            // the id is queryable for `scrollTo` even before the panel
            // expands.
            Color.clear
                .frame(height: 0)
                .id("\(holding.ticker)-end")
        }
        .clipped()
    }

    private var mainRow: some View {
        Button(action: onToggle) {
            HStack(spacing: 10 * scale) {
                holdingIcon
                tickerInfo
                Spacer()
                valueInfo

                if hasDetails {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .rotationEffect(.degrees(isExpanded ? -180 : 0))
                        .accessibilityHidden(true)
                }
            }
            .padding(.vertical, 8 * scale)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .allowsHitTesting(hasDetails)
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

            if let qty = holding.qty {
                Text(L10n.Home.holdingsShares(qty.asShareCount()))
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            } else if holding.isCash, holding.buyingPower != nil {
                Text(L10n.Home.holdingsAvailableToInvest)
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }

    private var valueInfo: some View {
        VStack(alignment: .trailing, spacing: 2 * scale) {
            Text(holding.marketValue.asCurrency())
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            if let pl = holding.unrealizedPl, let plpc = holding.unrealizedPlpc {
                Text("\(pl.asSignedCurrency()) (\(plpc.asSignedPercent()))")
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(pl >= 0 ? Color.sevinoPositive : Color.sevinoNegative)
            } else if holding.isCash, let buyingPower = holding.buyingPower {
                Text(buyingPower.asCurrency())
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
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

            if let changeToday = holding.changeToday,
               let changeTodayPct = holding.changeTodayPercent {
                detailRow(
                    label: L10n.Home.holdingsDaysGain,
                    value: "\(changeToday.asSignedCurrency()) (\(changeTodayPct.asSignedPercent()))",
                    isPositive: changeToday >= 0
                )
            }

            if let pl = holding.unrealizedPl, let plpc = holding.unrealizedPlpc {
                detailRow(
                    label: L10n.Home.holdingsTotalGain,
                    value: "\(pl.asSignedCurrency()) (\(plpc.asSignedPercent()))",
                    isPositive: pl >= 0
                )
            }

            if let avgCost = holding.avgEntryPrice {
                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(L10n.Home.holdingsAverageCost)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Text(avgCost.asCurrency())
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

    private func detailRow(label: String, value: String, isPositive: Bool) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer()
            Text(value)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(isPositive ? Color.sevinoPositive : Color.sevinoNegative)
        }
        .padding(.vertical, 6 * scale)
    }

}

#Preview("Holding rows") {
    VStack(spacing: 0) {
        HoldingRow(
            holding: Holding(
                ticker: "CASH",
                isCash: true,
                qty: nil,
                marketValue: Decimal(string: "2450.00")!,
                unrealizedPl: nil,
                unrealizedPlpc: nil,
                changeToday: nil,
                changeTodayPercent: nil,
                avgEntryPrice: nil,
                buyingPower: Decimal(string: "1980.00")!
            ),
            scale: 1,
            isExpanded: false,
            onToggle: {}
        )
        HoldingRow(
            holding: Holding(
                ticker: "TSLA",
                isCash: false,
                qty: Decimal(string: "5")!,
                marketValue: Decimal(string: "1250.00")!,
                unrealizedPl: Decimal(string: "250.00")!,
                unrealizedPlpc: Decimal(string: "0.25")!,
                changeToday: Decimal(string: "25.00")!,
                changeTodayPercent: Decimal(string: "0.0204")!,
                avgEntryPrice: Decimal(string: "200.00")!,
                buyingPower: nil
            ),
            scale: 1,
            isExpanded: false,
            onToggle: {}
        )
        HoldingRow(
            holding: Holding(
                ticker: "AMD",
                isCash: false,
                qty: Decimal(string: "10")!,
                marketValue: Decimal(string: "900.00")!,
                unrealizedPl: Decimal(string: "-100.00")!,
                unrealizedPlpc: Decimal(string: "-0.10")!,
                changeToday: Decimal(string: "-15.00")!,
                changeTodayPercent: Decimal(string: "-0.0164")!,
                avgEntryPrice: Decimal(string: "100.00")!,
                buyingPower: nil
            ),
            scale: 1,
            isExpanded: false,
            onToggle: {}
        )
    }
    .padding()
}
