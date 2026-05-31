import SwiftUI

struct HoldingsCard: View {
    let data: HoldingsCardData
    var scale: CGFloat = 1
    var onFilterTapped: (() -> Void)?

    var body: some View {
        HoldingsCardContent(data: data, scale: scale, onFilterTapped: onFilterTapped)
            .modifier(HoldingsCardShell(scale: scale))
    }
}

struct HoldingsCardContent: View {
    let data: HoldingsCardData
    var scale: CGFloat = 1
    var onFilterTapped: (() -> Void)?

    /// At most one row's detail panel is open at a time.
    @State private var expandedTicker: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            headerRow

            if data.holdings.isEmpty {
                emptyState
            } else if data.holdings.count > scrollThreshold {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(spacing: 12 * scale) {
                            ForEach(data.holdings) { holding in
                                row(for: holding, proxy: proxy)
                            }
                        }
                        .padding(.trailing, 16 * scale)
                    }
                    .frame(maxHeight: scrollMaxHeight)
                }
            } else {
                VStack(spacing: 12 * scale) {
                    ForEach(data.holdings) { holding in
                        row(for: holding, proxy: nil)
                    }
                }
            }
        }
    }

    private func toggle(_ ticker: String, proxy: ScrollViewProxy?) {
        let willExpand = expandedTicker != ticker
        // iOS 17's `withAnimation(_:_:completion:)` waits for the layout
        // pass for the new state, which is the only point at which
        // `scrollTo` sees the post-expansion frame. Runloop-tick deferrals
        // (`DispatchQueue.main.async`, `Task`, `RunLoop.main.perform`) race
        // the layout pass and break the bottom-edge first-tap case.
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            expandedTicker = willExpand ? ticker : nil
        } completion: {
            guard willExpand, let proxy else { return }
            withAnimation(.easeInOut(duration: 0.2)) {
                proxy.scrollTo("\(ticker)-end", anchor: nil)
            }
        }
    }

    @ViewBuilder
    private func row(for holding: Holding, proxy: ScrollViewProxy?) -> some View {
        HoldingRow(
            holding: holding,
            scale: scale,
            isExpanded: expandedTicker == holding.id,
            onToggle: { toggle(holding.id, proxy: proxy) }
        )
        .id(holding.id)
    }

    /// Includes the synthetic CASH row — at 6 total rows the modal is at
    /// the edge of a typical phone screen before any panel expands.
    private var scrollThreshold: Int { 6 }
    private var scrollMaxHeight: CGFloat { 500 * scale }

    private var headerRow: some View {
        HStack {
            Text(L10n.Home.holdingsTitle)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            Spacer()

            if let onFilterTapped {
                Button(action: onFilterTapped) {
                    HStack(spacing: 6 * scale) {
                        Text(data.displayOption)
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(Color.sevinoGreyContrast)

                        Image(systemName: "line.3.horizontal.decrease")
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(Color.sevinoGreyContrast)
                            .accessibilityHidden(true)
                    }
                }
            }
        }
        .zIndex(1)
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(L10n.Home.holdingsEmptyTitle, systemImage: "chart.pie")
        } description: {
            Text(L10n.Home.holdingsEmptyMessage)
        }
        .frame(maxWidth: .infinity)
    }
}

struct HoldingsCardShell: ViewModifier {
    let scale: CGFloat

    func body(content: Content) -> some View {
        content
            .padding(20 * scale)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .modifier(SevinoGlass.card)
            .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }
}

private struct HoldingsCardPreview: View {
    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 16) {
                    HoldingsCard(
                        data: HoldingsCardData(
                            holdings: [
                                Holding(
                                    ticker: "AAPL",
                                    isCash: false,
                                    qty: Decimal(10),
                                    marketValue: Decimal(string: "1820.50")!,
                                    unrealizedPl: Decimal(string: "120.50")!,
                                    unrealizedPlpc: Decimal(string: "0.0708")!,
                                    changeToday: Decimal(string: "12.30")!,
                                    changeTodayPercent: Decimal(string: "0.0068")!,
                                    avgEntryPrice: Decimal(string: "170.00")!,
                                    buyingPower: nil
                                ),
                                Holding(
                                    ticker: "CASH",
                                    isCash: true,
                                    qty: nil,
                                    marketValue: Decimal(string: "250.00")!,
                                    unrealizedPl: nil,
                                    unrealizedPlpc: nil,
                                    changeToday: nil,
                                    changeTodayPercent: nil,
                                    avgEntryPrice: nil,
                                    buyingPower: Decimal(string: "200.00")!
                                )
                            ],
                            displayOption: "Total Value"
                        ),
                        onFilterTapped: {}
                    )

                    HoldingsCard(
                        data: HoldingsCardData(holdings: [], displayOption: "Total Value")
                    )
                }
                .padding(16)
            }
        }
    }
}

#Preview("Dark") {
    HoldingsCardPreview()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    HoldingsCardPreview()
        .preferredColorScheme(.light)
}
