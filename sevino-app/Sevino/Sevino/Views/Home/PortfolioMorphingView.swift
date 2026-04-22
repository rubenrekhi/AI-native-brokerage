import SwiftUI

/// A single view that morphs between the small portfolio pill and the expanded modal.
struct PortfolioMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let viewModel: PortfolioViewModel
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: isExpanded ? 16 * scale : 0) {
                pillContent

                if isExpanded {
                    PortfolioExpandedContent(scale: scale, viewModel: viewModel)
                }
            }
            .padding(.horizontal, isExpanded ? 16 * scale : 12 * scale)
            .padding(.vertical, isExpanded ? 16 * scale : 0)
            .frame(maxWidth: isExpanded ? .infinity : nil, alignment: .leading)
            .frame(height: isExpanded ? nil : 36 * scale)
            .fixedSize(horizontal: !isExpanded, vertical: isExpanded)
            .modifier(isExpanded ? SevinoGlass.card : SevinoGlass.card)
            .clipShape(.rect(cornerRadius: isExpanded ? CardGlass.cornerRadius : 18 * scale))
            .frame(minHeight: isExpanded ? nil : 44 * scale)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(isExpanded)
        .accessibilityLabel(L10n.Home.portfolioAccessibility)
    }

    private var pillContent: some View {
        HStack(spacing: 8 * scale) {
            Text(viewModel.displayValue)
                .font(.system(size: isExpanded ? 36 * scale : 14 * scale, weight: isExpanded ? .bold : .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            if isExpanded {
                Text(L10n.Home.portfolioCurrency)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }

            if !isExpanded {
                VStack(spacing: -2 * scale) {
                    Image(systemName: "chevron.down")
                    Image(systemName: "chevron.down")
                }
                .font(.system(size: 9 * scale, weight: .bold))
                .foregroundStyle(viewModel.isDown ? Color.sevinoNegative : Color.sevinoPositive)
                .accessibilityHidden(true)
            }
        }
    }
}
