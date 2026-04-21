import SwiftUI

struct TradeCardView: View {
    let scale: CGFloat

    var body: some View {
        SevinoGlassContainer {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Spacer()
                    Text(L10n.Welcome.tradeUserMessage)
                        .font(.system(size: 14 * scale))
                        .foregroundStyle(Color.welcomeTextSecondary)
                        .padding(.horizontal, 16 * scale)
                        .padding(.vertical, 10 * scale)
                        .background(
                            Color.welcomeButtonDarkTint,
                            in: RoundedRectangle(cornerRadius: 16 * scale)
                        )
                }
                .padding(.bottom, 12 * scale)

                Text(L10n.Welcome.tradeAIResponse)
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.welcomeText)
                    .lineSpacing(3 * scale)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 12 * scale)

                SevinoGlassContainer {
                    VStack(alignment: .leading, spacing: 0) {
                        HStack(spacing: 10 * scale) {
                            StockLogoView(ticker: "AMD", size: 20 * scale)

                            VStack(alignment: .leading, spacing: 2 * scale) {
                                Text(L10n.Welcome.tradeStockName)
                                    .font(.system(size: 14 * scale, weight: .semibold))
                                    .foregroundStyle(Color.welcomeText)
                                Text(L10n.Welcome.tradeStockTicker)
                                    .font(.system(size: 12 * scale))
                                    .foregroundStyle(Color.welcomeTextDimmed)
                            }
                        }
                        .padding(.bottom, 12 * scale)

                        HStack {
                            Text(L10n.Welcome.tradeEstimatedTotal)
                                .font(.system(size: 14 * scale))
                                .foregroundStyle(Color.welcomeTextDimmed)
                            Spacer()
                            Text(L10n.Welcome.tradeEstimatedValue)
                                .font(.system(size: 20 * scale, weight: .bold))
                                .foregroundStyle(Color.welcomeText)
                        }
                        .padding(.bottom, 14 * scale)

                        Text(L10n.Welcome.tradeHoldToConfirm)
                            .font(.system(size: 14 * scale, weight: .semibold))
                            .foregroundStyle(Color.welcomeText)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12 * scale)
                            .background(Color.welcomeTradeConfirm, in: Capsule())
                    }
                    .padding(12 * scale)
                    .modifier(SevinoGlass.card)
                }
            }
            .padding(16 * scale)
            .modifier(SevinoGlass.card)
        }
    }
}
