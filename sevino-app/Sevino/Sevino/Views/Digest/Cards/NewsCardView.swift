import SwiftUI

struct NewsCardView: View {
    let card: NewsDigestCard
    let scale: CGFloat

    @State private var safariURL: DigestSafariURL?

    var body: some View {
        Button(action: openNews) {
            VStack(alignment: .leading, spacing: 16 * scale) {
                HStack(spacing: 8 * scale) {
                    Text(card.source)
                        .font(.system(size: 13 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoPrimary)

                    Text(DigestCardFormatting.timeAgo(card.publishedAt))
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoPrimary.opacity(0.56))

                    Spacer()

                    if let symbol = card.symbol {
                        DigestPill(text: symbol, color: .sevinoInfo, scale: scale)
                    }
                }

                Text(card.headline)
                    .font(.dmSerif(size: 34 * scale))
                    .foregroundStyle(Color.sevinoPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(card.summary)
                    .font(.system(size: 16 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.74))
                    .fixedSize(horizontal: false, vertical: true)

                Spacer(minLength: 0)

                HStack(spacing: 6 * scale) {
                    Text(L10n.Digest.newsOpenStory)
                    Image(systemName: "safari")
                        .accessibilityHidden(true)
                }
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoInfo)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .sheet(item: $safariURL) { item in
            DigestSafariView(url: item.url)
        }
    }

    private func openNews() {
        guard let url = URL(string: card.url) else { return }
        safariURL = DigestSafariURL(url: url)
    }
}

#Preview {
    NewsCardView(
        card: NewsDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["AAPL"],
            cardContext: [:],
            symbol: "AAPL",
            headline: "Apple shares moved after services revenue update",
            source: "MarketWire",
            url: "https://example.com/news",
            publishedAt: Date(timeIntervalSinceNow: -3_600),
            summary: "The company reported stronger services revenue while hardware sales were little changed."
        ),
        scale: 1
    )
    .padding()
}
