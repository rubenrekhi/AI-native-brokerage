import SwiftUI

struct RadarRefreshCardView: View {
    let card: RadarRefreshDigestCard
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 22 * scale) {
            VStack(alignment: .leading, spacing: 8 * scale) {
                Text(L10n.Digest.radarRefreshedTitle)
                    .font(.dmSerif(size: 40 * scale))
                    .foregroundStyle(Color.sevinoPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(L10n.Digest.radarUpdated(DigestCardFormatting.dateTime(card.refreshedAt)))
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.58))
            }

            HStack(spacing: 12 * scale) {
                countBlock(title: L10n.Digest.radarNew, count: card.newCount, color: .sevinoPositive)
                countBlock(title: L10n.Digest.radarRemoved, count: card.removedCount, color: .sevinoNegative)
            }

            Spacer(minLength: 0)
        }
    }

    private func countBlock(title: String, count: Int, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text("\(count)")
                .font(.dmSerif(size: 44 * scale))
                .foregroundStyle(color)
                .lineLimit(1)

            Text(title)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPrimary.opacity(0.68))
        }
        .padding(16 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.sevinoPrimary.opacity(0.05), in: .rect(cornerRadius: 8 * scale))
    }
}

#Preview {
    RadarRefreshCardView(
        card: RadarRefreshDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: [],
            cardContext: [:],
            refreshedAt: Date(timeIntervalSince1970: 1_779_635_600),
            newCount: 3,
            removedCount: 1
        ),
        scale: 1
    )
    .padding()
}
