import SwiftUI

struct EarningsResultCardView: View {
    let card: EarningsResultDigestCard
    let scale: CGFloat

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16 * scale) {
                HStack(alignment: .center, spacing: 12 * scale) {
                    DigestTickerHeader(symbol: card.symbol, name: card.name, scale: scale)
                    Spacer()
                    gradeBadge
                }

                VStack(spacing: 0) {
                    DigestInfoRow(label: L10n.Digest.earningsEpsActual, value: card.epsActual?.asCurrency() ?? "-", scale: scale)
                    DigestInfoRow(label: L10n.Digest.earningsEpsEstimate, value: card.epsEstimate?.asCurrency() ?? "-", scale: scale)
                    Divider().background(Color.sevinoPrimary.opacity(0.12))
                    DigestInfoRow(label: L10n.Digest.earningsRevenueActual, value: card.revActual?.asCurrency() ?? "-", scale: scale)
                    DigestInfoRow(label: L10n.Digest.earningsRevenueEstimate, value: card.revEstimate?.asCurrency() ?? "-", scale: scale)
                }

                if let stockReactionPct = card.stockReactionPct {
                    HStack(spacing: 8 * scale) {
                        Image(systemName: stockReactionPct >= 0 ? "arrow.up.right" : "arrow.down.right")
                            .font(.system(size: 13 * scale, weight: .bold))
                            .foregroundStyle(stockReactionPct.digestSignedColor)
                            .accessibilityHidden(true)

                        Text(L10n.Digest.earningsStockReaction(stockReactionPct.asSignedPercent()))
                            .font(.system(size: 16 * scale, weight: .semibold))
                            .foregroundStyle(stockReactionPct.digestSignedColor)
                    }
                    .padding(.vertical, 4 * scale)
                }

                if !card.beatMissHighlights.isEmpty {
                    VStack(alignment: .leading, spacing: 8 * scale) {
                        ForEach(card.beatMissHighlights, id: \.self) { highlight in
                            HStack(alignment: .top, spacing: 8 * scale) {
                                Circle()
                                    .fill(Color.sevinoPrimary.opacity(0.7))
                                    .frame(width: 5 * scale, height: 5 * scale)
                                    .padding(.top, 7 * scale)
                                Text(highlight)
                                    .font(.system(size: 15 * scale, weight: .medium))
                                    .foregroundStyle(Color.sevinoPrimary.opacity(0.78))
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
            }
        }
        .scrollIndicators(.hidden)
    }

    private var gradeBadge: some View {
        Text(card.grade)
            .font(.dmSerif(size: 36 * scale))
            .foregroundStyle(Color.sevinoPrimary)
            .frame(width: 66 * scale, height: 66 * scale)
            .background(Color.sevinoAccent.opacity(0.45), in: .circle)
            .overlay(
                Circle().stroke(Color.sevinoPrimary.opacity(0.08), lineWidth: 1)
            )
    }
}

#Preview {
    EarningsResultCardView(
        card: EarningsResultDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["AMZN"],
            cardContext: [:],
            symbol: "AMZN",
            name: "Amazon",
            grade: "B+",
            epsActual: 1.23,
            epsEstimate: 1.10,
            revActual: 1_000_000_000,
            revEstimate: 980_000_000,
            stockReactionPct: 0.052,
            beatMissHighlights: ["EPS beat estimates", "Revenue came in above consensus"]
        ),
        scale: 1
    )
    .padding()
}
