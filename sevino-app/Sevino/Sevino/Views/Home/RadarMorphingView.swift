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
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .buttonStyle(.bouncePill)
        .modifier(SevinoGlass.navCircleClear)
        .contentShape(.rect)
        .frame(minWidth: 44 * scale, minHeight: 44 * scale)
        .accessibilityLabel(L10n.Home.watchlistAccessibility)
    }

    private var expandedCard: some View {
        RadarCard(
            data: RadarCardData(items: viewModel.radarItems),
            scale: scale,
            onToggleStar: { id in viewModel.toggleStar(for: id) }
        )
        .transition(.asymmetric(insertion: .opacity, removal: .identity))
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
