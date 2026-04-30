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
            displayValue: viewModel.displayValue,
            isDown: viewModel.isDown,
            gainText: viewModel.gainText,
            periodLabel: viewModel.periodLabel,
            chartPoints: viewModel.chartPoints,
            selectedTimeRange: viewModel.selectedTimeRange
        )
    }

    private var pillButton: some View {
        Button(action: onTap) {
            HStack(spacing: 6 * scale) {
                Text(viewModel.displayValue)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)

                VStack(spacing: -2 * scale) {
                    Image(systemName: "chevron.down")
                    Image(systemName: "chevron.down")
                }
                .font(.system(size: 8 * scale, weight: .bold))
                .foregroundStyle(viewModel.isDown ? Color.sevinoNegative : Color.sevinoPositive)
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
