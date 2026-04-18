import SwiftUI

struct RadarMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let viewModel: HomeViewModel
    let onTap: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: isExpanded ? .leading : .center, spacing: 0) {
            if isExpanded {
                expandedContent
            } else {
                pillContent
            }
        }
        .padding(isExpanded ? 20 * scale : 0)
        .frame(maxWidth: isExpanded ? .infinity : nil, alignment: isExpanded ? .leading : .center)
        .fixedSize(horizontal: !isExpanded, vertical: !isExpanded)
        .modifier(SaturnGlass.card)
        .clipShape(.rect(cornerRadius: isExpanded ? CardGlass.cornerRadius : 50 * scale))
        .gesture(isExpanded ? nil : TapGesture().onEnded { onTap() })
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(L10n.Home.watchlistAccessibility)
    }

    private var pillContent: some View {
        Image(systemName: "eye")
            .font(.system(size: 16 * scale, weight: .medium))
            .foregroundStyle(Color.saturnSecondary)
            .frame(width: 36 * scale, height: 36 * scale)
    }

    private var expandedContent: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            headerSection

            ForEach(viewModel.radarItems) { item in
                RadarItemRow(item: item, scale: scale, onToggleStar: {
                    viewModel.toggleRadarStar(id: item.id)
                })
            }
        }
    }

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(L10n.Home.radarTitle)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.saturnSecondary)

            Text(L10n.Home.radarSubtitle)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.saturnSecondary)

            Text(L10n.Home.radarDisclaimer)
                .font(.system(size: 11 * scale))
                .foregroundStyle(Color.saturnGreyContrast)
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
                        .foregroundStyle(Color.saturnSecondary)

                    Text(item.description)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.saturnGreyContrast)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                Button(L10n.Home.radarStarAccessibility, systemImage: item.isStarred ? "star.fill" : "star", action: onToggleStar)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale))
                    .foregroundStyle(item.isStarred ? Color.homeStarActive : Color.saturnGreyContrast)
            }

            HStack(spacing: 8 * scale) {
                Text(item.price)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.saturnSecondary)

                Text(item.changePercent)
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(item.isPositive ? Color.saturnPositive : Color.saturnNegative)

                Spacer()

                Text(L10n.Home.radarExpires(item.expiresIn))
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(Color.saturnGreyContrast)
            }
        }
        .padding(12 * scale)
        .background(Color.saturnGreyAccent.opacity(0.1), in: .rect(cornerRadius: 14 * scale))
    }
}

#Preview("Dark") {
    ZStack {
        Color.saturnPrimary.ignoresSafeArea()
        RadarMorphingView(
            scale: 1,
            isExpanded: true,
            viewModel: {
                let vm = HomeViewModel()
                vm.loadGreeting()
                return vm
            }(),
            onTap: {},
            onDismiss: {}
        )
        .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    ZStack {
        Color.saturnPrimary.ignoresSafeArea()
        RadarMorphingView(
            scale: 1,
            isExpanded: true,
            viewModel: {
                let vm = HomeViewModel()
                vm.loadGreeting()
                return vm
            }(),
            onTap: {},
            onDismiss: {}
        )
        .padding(16)
    }
    .preferredColorScheme(.light)
}
