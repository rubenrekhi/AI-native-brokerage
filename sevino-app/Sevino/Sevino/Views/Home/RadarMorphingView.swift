import SwiftUI

struct RadarMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let isHidden: Bool
    let viewModel: RadarViewModel
    let onTap: () -> Void
    let onDismiss: () -> Void

    @Namespace private var morphNamespace

    var body: some View {
        Group {
            if isExpanded {
                expandedCard
            } else if !isHidden {
                pillButton
            }
        }
        .modifier(GlassMorphID(id: "radar", namespace: morphNamespace))
    }

    private var pillButton: some View {
        Button(action: onTap) {
            Image(systemName: "eye")
                .font(.system(size: 16 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 44 * scale, height: 44 * scale)
        }
        .buttonStyle(.bouncePill)
        .modifier(SevinoGlass.navCircleClear)
        .accessibilityLabel(L10n.Home.watchlistAccessibility)
    }

    private var expandedCard: some View {
        expandedContent
            .padding(20 * scale)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .modifier(SevinoGlass.card)
            .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }

    private var expandedContent: some View {
        LazyVStack(alignment: .leading, spacing: 12 * scale) {
            headerSection

            if viewModel.radarItems.isEmpty {
                emptyState
            } else {
                ForEach(viewModel.radarItems) { item in
                    RadarItemRow(item: item, scale: scale, onToggleStar: {
                        viewModel.toggleStar(for: item.id)
                    })
                }
            }
        }
        .transition(.asymmetric(insertion: .opacity, removal: .identity))
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(L10n.Home.radarEmptyTitle, systemImage: "eye")
        } description: {
            Text(L10n.Home.radarEmptyMessage)
        }
        .frame(maxWidth: .infinity)
    }

    private var headerSection: some View {
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

private struct RadarItemRow: View {
    let item: RadarItem
    let scale: CGFloat
    let onToggleStar: () -> Void

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

                Button(L10n.Home.radarStarAccessibility, systemImage: item.isStarred ? "star.fill" : "star", action: onToggleStar)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale))
                    .foregroundStyle(item.isStarred ? Color.homeStarActive : Color.sevinoGreyContrast)
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

private struct RadarMorphingPreview: View {
    @State private var viewModel = RadarViewModel()

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()
            RadarMorphingView(
                scale: 1,
                isExpanded: true,
                isHidden: false,
                viewModel: viewModel,
                onTap: {},
                onDismiss: {}
            )
            .padding(16)
        }
        .task { await viewModel.loadRadar() }
    }
}

#Preview("Dark") {
    RadarMorphingPreview()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    RadarMorphingPreview()
        .preferredColorScheme(.light)
}
