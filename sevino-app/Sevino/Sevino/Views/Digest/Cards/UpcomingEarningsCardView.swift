import SwiftUI

struct UpcomingEarningsCardView: View {
    let card: UpcomingEarningsDigestCard
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 22 * scale) {
            DigestTickerHeader(symbol: card.symbol, name: card.name, scale: scale)

            VStack(alignment: .leading, spacing: 8 * scale) {
                Text(card.relativeLabel.capitalized)
                    .font(.dmSerif(size: 52 * scale))
                    .foregroundStyle(Color.sevinoPrimary)
                    .lineLimit(2)
                    .minimumScaleFactor(0.72)

                Text(L10n.Digest.upcomingReports(DigestCardFormatting.dateTime(card.reportsAt)))
                    .font(.system(size: 16 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.62))
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)
        }
    }
}

#Preview {
    UpcomingEarningsCardView(
        card: UpcomingEarningsDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["META"],
            cardContext: [:],
            symbol: "META",
            name: "Meta Platforms",
            reportsAt: Date(timeIntervalSince1970: 1_780_117_200),
            relativeLabel: "Thursday"
        ),
        scale: 1
    )
    .padding()
}
