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

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            headerRow

            if data.holdings.isEmpty {
                emptyState
            } else {
                LazyVStack(spacing: 12 * scale) {
                    ForEach(data.holdings) { holding in
                        HoldingRow(holding: holding, scale: scale)
                    }
                }
            }
        }
    }

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
                                    shares: "10",
                                    value: "$1,820.50",
                                    gainLossText: "+$120.50 (7.08%)",
                                    isPositive: true,
                                    daysGain: "+$12.30",
                                    daysGainPercent: "0.68%",
                                    totalGain: "+$120.50",
                                    totalGainPercent: "7.08%",
                                    averageCost: "$170.00"
                                ),
                                Holding(
                                    ticker: "Cash",
                                    isCash: true,
                                    shares: nil,
                                    value: "$250.00",
                                    gainLossText: nil,
                                    isPositive: nil,
                                    daysGain: nil,
                                    daysGainPercent: nil,
                                    totalGain: nil,
                                    totalGainPercent: nil,
                                    averageCost: nil
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
