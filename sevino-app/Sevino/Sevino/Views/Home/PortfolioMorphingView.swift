import SwiftUI

/// A single view that morphs between the small portfolio pill and the expanded modal.
struct PortfolioMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let isHidden: Bool
    let viewModel: PortfolioViewModel
    let onTap: () -> Void

    @Namespace private var morphNamespace

    var body: some View {
        Group {
            if isExpanded {
                PortfolioCard(
                    data: cardData,
                    scale: scale,
                    isInteractive: true,
                    onTimeRangeChanged: viewModel.setTimeRange
                )
            } else if !isHidden {
                pillButton
            }
        }
        .modifier(GlassMorphID(id: "portfolio", namespace: morphNamespace))
    }

    private var cardData: PortfolioCardData {
        PortfolioCardData(
            equity: viewModel.equity,
            currency: viewModel.currency,
            gainAbs: viewModel.gainAbs,
            gainPct: viewModel.gainPct,
            chartPoints: viewModel.chartPoints,
            chartValues: viewModel.chartValues,
            chartDates: viewModel.chartDates,
            selectedTimeRange: viewModel.selectedTimeRange,
            hasLoaded: viewModel.hasLoaded
        )
    }

    private var pillButton: some View {
        Button(action: onTap) {
            HStack(spacing: 6 * scale) {
                Group {
                    if viewModel.hasLoaded {
                        Text(viewModel.equity.asCurrency(currencyCode: viewModel.currency))
                    } else {
                        Text(verbatim: "—")
                    }
                }
                .font(.system(size: 13 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

                VStack(spacing: -2 * scale) {
                    // Direction tracks the sign of the currently-loaded
                    // range's gain (defaults to 1M). Pointing up = green,
                    // down = red — must agree, otherwise the icon
                    // contradicts the color.
                    let chevron = viewModel.gainAbs < 0 ? "chevron.down" : "chevron.up"
                    Image(systemName: chevron)
                    Image(systemName: chevron)
                }
                .font(.system(size: 8 * scale, weight: .bold))
                .foregroundStyle(viewModel.gainAbs < 0 ? Color.sevinoNegative : Color.sevinoPositive)
                .accessibilityHidden(true)
            }
            .padding(.horizontal, 12 * scale)
            .frame(height: 36 * scale)
        }
        .buttonStyle(.bouncePill)
        .modifier(SevinoGlass.navPillClear)
        .contentShape(.rect)
        .frame(minHeight: 44 * scale)
        .accessibilityLabel(L10n.Home.portfolioAccessibility)
    }
}
