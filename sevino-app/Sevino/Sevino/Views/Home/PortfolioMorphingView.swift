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
                expandedCard
            } else if !isHidden {
                pillButton
            }
        }
        .modifier(GlassMorphID(id: "portfolio", namespace: morphNamespace))
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

    private var expandedCard: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16 * scale) {
                HStack(spacing: 8 * scale) {
                    Text(viewModel.displayValue)
                        .font(.system(size: 36 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)

                    Text(L10n.Home.portfolioCurrency)
                        .font(.system(size: 18 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }

                PortfolioExpandedContent(scale: scale, viewModel: viewModel)
            }
            .padding(16 * scale)
        }
        .refreshable {
            await viewModel.loadPortfolio()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }
}
