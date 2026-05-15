import SwiftUI

struct AttachedContextCardView: View {
    let context: AttachedContext
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            HStack(spacing: 6 * scale) {
                Image(systemName: iconName)
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .accessibilityHidden(true)
                Text(title)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
            }

            contentView
        }
        .padding(12 * scale)
        .background(GenUICardBackground(cornerRadius: 16 * scale))
        .padding(.horizontal, 16 * scale)
    }

    private var iconName: String {
        switch context {
        case .portfolio: "chart.line.uptrend.xyaxis"
        case .holdings: "list.bullet"
        case .funding: "dollarsign.circle"
        case .radar: "antenna.radiowaves.left.and.right"
        }
    }

    private var title: String {
        switch context {
        case .portfolio: L10n.Chat.contextPortfolio
        case .holdings: L10n.Chat.contextHoldings
        case .funding: L10n.Chat.contextCash
        case .radar: L10n.Chat.contextRadar
        }
    }

    @ViewBuilder
    private var contentView: some View {
        switch context {
        case .portfolio(let equity, let currency, let gainAbs, let gainPct, _):
            HStack(spacing: 12 * scale) {
                VStack(alignment: .leading, spacing: 2 * scale) {
                    Text(equity.asCurrency(currencyCode: currency))
                        .font(.system(size: 18 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)
                    Text(gainAbs.asSignedCurrency(currencyCode: currency) + " (" + gainPct.asSignedPercent() + ")")
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(gainAbs >= 0 ? Color.sevinoPositive : Color.sevinoNegative)
                }
                Spacer()
            }

        case .holdings(let holdings):
            VStack(alignment: .leading, spacing: 4 * scale) {
                ForEach(holdings.prefix(5)) { h in
                    HStack {
                        Text(h.ticker)
                            .font(.system(size: 13 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)
                        Spacer()
                        Text(h.marketValue.asCurrency())
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(Color.sevinoGreyContrast)
                    }
                }
                if holdings.count > 5 {
                    Text(L10n.Chat.moreItems(holdings.count - 5))
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }

        case .funding(let balance, let apy, let buyingPower):
            VStack(alignment: .leading, spacing: 4 * scale) {
                HStack {
                    Text(L10n.Chat.fundingBalance)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Spacer()
                    Text(balance.asCurrency())
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                }
                HStack {
                    Text(L10n.Chat.fundingApy)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Spacer()
                    Text(apy.asSignedPercent())
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoPositive)
                }
                HStack {
                    Text(L10n.Chat.fundingBuyingPower)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Spacer()
                    Text(buyingPower.asCurrency())
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                }
            }

        case .radar(let items):
            VStack(alignment: .leading, spacing: 4 * scale) {
                ForEach(items.prefix(5)) { item in
                    HStack {
                        Text(item.ticker)
                            .font(.system(size: 13 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)
                        Spacer()
                        Text(item.changePercent)
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(item.isPositive ? Color.sevinoPositive : Color.sevinoNegative)
                    }
                }
                if items.count > 5 {
                    Text(L10n.Chat.moreItems(items.count - 5))
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
        }
    }
}

#Preview("Portfolio") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        AttachedContextCardView(
            context: .portfolio(equity: 12500.50, currency: "USD", gainAbs: 350.25, gainPct: 0.0288, timeRange: "1M"),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Holdings") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        AttachedContextCardView(
            context: .holdings(holdings: [
                HoldingSummary(ticker: "AAPL", marketValue: 5400, unrealizedPl: 320),
                HoldingSummary(ticker: "MSFT", marketValue: 3200, unrealizedPl: -50),
            ]),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}
