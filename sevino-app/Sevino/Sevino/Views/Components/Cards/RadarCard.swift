import SwiftUI

struct RadarCard: View {
    let data: RadarCardData
    var scale: CGFloat = 1
    var onToggleStar: ((String) -> Void)?

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 12 * scale) {
            RadarCardHeader(scale: scale)

            if data.items.isEmpty {
                RadarCardEmptyState()
            } else {
                ForEach(data.items) { item in
                    RadarItemRow(
                        item: item,
                        scale: scale,
                        onToggleStar: onToggleStar
                    )
                }
            }
        }
        .padding(20 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }
}

private struct RadarCardHeader: View {
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(L10n.Home.radarTitle)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            Text(L10n.Home.radarSubtitle)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)

            Text(L10n.Home.radarDisclaimer)
                .font(.system(size: 11 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 2 * scale)
        }
    }
}

private struct RadarCardEmptyState: View {
    var body: some View {
        ContentUnavailableView {
            Label(L10n.Home.radarEmptyTitle, systemImage: "eye")
        } description: {
            Text(L10n.Home.radarEmptyMessage)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct RadarItemRow: View {
    let item: RadarItem
    let scale: CGFloat
    let onToggleStar: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            HStack(alignment: .top, spacing: 10 * scale) {
                StockLogoView(ticker: item.ticker, size: 28 * scale)

                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(item.ticker)
                        .font(.system(size: 16 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)

                    Text(item.description)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                Button(
                    L10n.Home.radarStarAccessibility,
                    systemImage: item.isStarred ? "star.fill" : "star"
                ) {
                    onToggleStar?(item.id)
                }
                .labelStyle(.iconOnly)
                .font(.system(size: 18 * scale))
                .foregroundStyle(item.isStarred ? Color.homeStarActive : Color.sevinoGreyContrast)
                .contentShape(.rect)
                .frame(minWidth: 44 * scale, minHeight: 44 * scale)
                .disabled(onToggleStar == nil)
                .opacity(onToggleStar == nil ? 0 : 1)
            }

            HStack(spacing: 8 * scale) {
                Text(item.price)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)

                Text(item.changePercent)
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(item.isPositive ? Color.sevinoPositive : Color.sevinoNegative)

                Spacer()

                Text(L10n.Home.radarExpires(item.expiresIn))
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
            .padding(.leading, (28 + 10) * scale)
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.1), in: .rect(cornerRadius: 14 * scale))
    }
}

private let radarCardMockItems: [RadarItem] = [
    RadarItem(
        ticker: "AAPL",
        description: "Apple earnings beat expectations",
        price: "$189.42",
        changePercent: "+1.24%",
        isPositive: true,
        expiresIn: "2h",
        isStarred: true
    ),
    RadarItem(
        ticker: "TSLA",
        description: "Tesla deliveries miss guidance",
        price: "$242.10",
        changePercent: "-3.10%",
        isPositive: false,
        expiresIn: "45m",
        isStarred: false
    )
]

#Preview("Populated") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        RadarCard(
            data: RadarCardData(items: radarCardMockItems),
            onToggleStar: { _ in }
        )
        .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Read-only") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        RadarCard(data: RadarCardData(items: radarCardMockItems))
            .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Empty") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        RadarCard(data: RadarCardData(items: []))
            .padding(16)
    }
    .preferredColorScheme(.dark)
}
