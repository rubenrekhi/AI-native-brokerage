import SwiftUI

struct MarketContextCardView: View {
    let card: MarketContextDigestCard
    let scale: CGFloat

    private var directionText: String {
        switch card.direction {
        case "up": return L10n.Digest.marketDirectionUp
        case "down": return L10n.Digest.marketDirectionDown
        case "mixed": return L10n.Digest.marketDirectionMixed
        default: return card.direction.capitalized
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20 * scale) {
            HStack(spacing: 10 * scale) {
                DigestMetricChip(
                    label: "SPY",
                    value: card.sp500ChangePct.asSignedPercent(),
                    color: card.sp500ChangePct.digestSignedColor,
                    scale: scale
                )

                DigestMetricChip(
                    label: "QQQ",
                    value: card.nasdaqChangePct.asSignedPercent(),
                    color: card.nasdaqChangePct.digestSignedColor,
                    scale: scale
                )
            }

            Text(directionText)
                .font(.dmSerif(size: 36 * scale))
                .foregroundStyle(Color.sevinoPrimary)
                .fixedSize(horizontal: false, vertical: true)

            Text(card.summary)
                .font(.system(size: 17 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoPrimary.opacity(0.74))
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)
        }
    }
}

#Preview {
    MarketContextCardView(
        card: MarketContextDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: [],
            cardContext: [:],
            direction: "mixed",
            sp500ChangePct: 0.004,
            nasdaqChangePct: -0.002,
            summary: "Semiconductors lagged while defensive sectors held firmer into the close."
        ),
        scale: 1
    )
    .padding()
}
