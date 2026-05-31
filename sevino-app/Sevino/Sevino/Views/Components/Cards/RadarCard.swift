import SwiftUI

struct RadarCard: View {
    let data: RadarCardData
    var scale: CGFloat = 1
    @Binding var activeTab: RadarTab
    var onToggleStar: ((UUID) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            RadarCardHeader(scale: scale)

            RadarTabStrip(
                activeTab: $activeTab,
                newCount: data.newItems.count,
                starredCount: data.starredItems.count,
                scale: scale
            )

            tabContent
                .transition(.opacity)
                .id(activeTab)

            RadarDisclaimer(scale: scale)
        }
        .padding(20 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }

    @ViewBuilder
    private var tabContent: some View {
        switch activeTab {
        case .new:
            newTab
        case .starred:
            starredTab
        }
    }

    @ViewBuilder
    private var newTab: some View {
        switch data.newTabState {
        case .populated:
            RadarItemList(items: data.newItems, scale: scale, onToggleStar: onToggleStar)
        case .firstBatch:
            RadarEmptyState(
                systemImage: "sparkles",
                message: L10n.Home.radarEmptyNewFirstBatch,
                scale: scale
            )
        case .reviewed(let weekday):
            RadarEmptyState(
                systemImage: "checkmark.circle",
                message: L10n.Home.radarEmptyNewReviewed(weekday),
                scale: scale
            )
        }
    }

    @ViewBuilder
    private var starredTab: some View {
        if data.starredItems.isEmpty {
            RadarEmptyState(
                systemImage: "star",
                message: L10n.Home.radarEmptyStarred,
                scale: scale
            )
        } else {
            RadarItemList(items: data.starredItems, scale: scale, onToggleStar: onToggleStar)
        }
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
        }
    }
}

private struct RadarDisclaimer: View {
    let scale: CGFloat

    var body: some View {
        Text(L10n.Home.radarDisclaimer)
            .font(.system(size: 11 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct RadarTabStrip: View {
    @Binding var activeTab: RadarTab
    let newCount: Int
    let starredCount: Int
    let scale: CGFloat

    @State private var totalWidth: CGFloat = 0

    private var itemWidth: CGFloat { totalWidth / CGFloat(RadarTab.allCases.count) }

    private var indicatorOffset: CGFloat {
        guard let idx = RadarTab.allCases.firstIndex(of: activeTab) else { return 0 }
        return CGFloat(idx) * itemWidth
    }

    var body: some View {
        ZStack(alignment: .leading) {
            if totalWidth > 0 {
                Capsule()
                    .fill(Color.sevinoGreyAccent.opacity(0.35))
                    .frame(width: itemWidth)
                    .offset(x: indicatorOffset)
                    .allowsHitTesting(false)
            }

            HStack(spacing: 0) {
                tab(.new, title: L10n.Home.radarTabNew, count: newCount)
                tab(.starred, title: L10n.Home.radarTabStarred, count: starredCount)
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { totalWidth = $0 }
        .padding(4 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.12), in: .capsule)
        .sensoryFeedback(.selection, trigger: activeTab)
    }

    private func tab(_ target: RadarTab, title: String, count: Int) -> some View {
        let isActive = activeTab == target
        return Button {
            withAnimation(.spring(duration: 0.35, bounce: 0.2)) {
                activeTab = target
            }
        } label: {
            HStack(spacing: 6 * scale) {
                Text(title)
                    .font(.system(size: 14 * scale, weight: .semibold))

                Text("\(count)")
                    .font(.system(size: 12 * scale, weight: .semibold))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .foregroundStyle(isActive ? Color.sevinoSecondary : Color.sevinoGreyContrast)
                    .padding(.horizontal, 7 * scale)
                    .padding(.vertical, 2 * scale)
                    .background(
                        (isActive ? Color.sevinoSecondary : Color.sevinoGreyContrast).opacity(0.15),
                        in: .capsule
                    )
                    .animation(.snappy, value: count)
            }
            .foregroundStyle(isActive ? Color.sevinoSecondary : Color.sevinoGreyContrast)
            .frame(maxWidth: .infinity, minHeight: 40 * scale)
            .contentShape(.capsule)
        }
        .buttonStyle(.plain)
        .disabled(isActive)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
        .accessibilityValue("\(count)")
        .accessibilityAddTraits(isActive ? .isSelected : [])
    }
}

private struct RadarItemList: View {
    let items: [RadarItem]
    let scale: CGFloat
    let onToggleStar: ((UUID) -> Void)?

    private var scrollThreshold: Int { 5 }
    private var scrollMaxHeight: CGFloat { 380 * scale }

    var body: some View {
        Group {
            if items.count > scrollThreshold {
                ScrollView {
                    rows.padding(.trailing, 4 * scale)
                }
                .frame(maxHeight: scrollMaxHeight)
            } else {
                rows
            }
        }
        .animation(.spring(duration: 0.35, bounce: 0.1), value: items)
    }

    private var rows: some View {
        VStack(spacing: 10 * scale) {
            ForEach(items) { item in
                RadarItemRow(item: item, scale: scale, onToggleStar: onToggleStar)
                    .transition(.opacity.combined(with: .scale(scale: 0.97)))
            }
        }
    }
}

private struct RadarEmptyState: View {
    let systemImage: String
    let message: String
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 10 * scale) {
            Image(systemName: systemImage)
                .font(.system(size: 26 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(message)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 32 * scale)
    }
}

private struct RadarItemRow: View {
    let item: RadarItem
    let scale: CGFloat
    let onToggleStar: ((UUID) -> Void)?

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
                .contentTransition(.symbolEffect(.replace))
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

                if !item.expiresIn.isEmpty {
                    Text(L10n.Home.radarExpires(item.expiresIn))
                        .font(.system(size: 11 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
            .padding(.leading, (28 + 10) * scale)
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.1), in: .rect(cornerRadius: 14 * scale))
    }
}

private let radarNewMockItems: [RadarItem] = [
    RadarItem(
        ticker: "NVDA",
        description: "AI chip giant with record data center revenue.",
        source: .aiGenerated,
        relevanceScore: 0.92,
        isStarred: false,
        price: "$892.41", changePercent: "+2.67%", isPositive: true, expiresIn: "6 days"
    ),
    RadarItem(
        ticker: "TSLA",
        description: "Automotive tech leader, earnings in 2 days.",
        source: .aiGenerated,
        relevanceScore: 0.81,
        isStarred: false,
        price: "$274.63", changePercent: "-1.24%", isPositive: false, expiresIn: "6 days"
    )
]

private let radarStarredMockItems: [RadarItem] = [
    RadarItem(
        ticker: "AAPL",
        description: "iPhone maker nearing $4T market cap.",
        source: .aiGenerated,
        isStarred: true,
        price: "$198.11", changePercent: "-0.43%", isPositive: false, expiresIn: ""
    )
]

private struct RadarCardPreview: View {
    @State private var activeTab: RadarTab = .new
    let data: RadarCardData

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()
            RadarCard(data: data, activeTab: $activeTab, onToggleStar: { _ in })
                .padding(16)
        }
    }
}

#Preview("Both tabs") {
    RadarCardPreview(
        data: RadarCardData(
            newItems: radarNewMockItems,
            starredItems: radarStarredMockItems,
            nextRefreshWeekday: "Monday"
        )
    )
    .preferredColorScheme(.dark)
}

#Preview("New reviewed") {
    RadarCardPreview(
        data: RadarCardData(
            newItems: [],
            starredItems: radarStarredMockItems,
            nextRefreshWeekday: "Thursday"
        )
    )
    .preferredColorScheme(.dark)
}

#Preview("First batch") {
    RadarCardPreview(
        data: RadarCardData(newItems: [], starredItems: [], nextRefreshWeekday: nil)
    )
    .preferredColorScheme(.dark)
}
