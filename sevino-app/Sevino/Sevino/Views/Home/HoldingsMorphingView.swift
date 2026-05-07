import SwiftUI

struct HoldingsMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let isHidden: Bool
    let viewModel: HoldingsViewModel
    @Binding var showFilter: Bool
    let onTap: () -> Void
    let onDismiss: () -> Void

    @Namespace private var morphNamespace

    var body: some View {
        card
    }

    private var card: some View {
        Group {
            if isExpanded {
                expandedCard
            } else if !isHidden {
                pillButton
            }
        }
        .modifier(GlassMorphID(id: "holdings", namespace: morphNamespace))
    }

    private var pillButton: some View {
        Button(action: onTap) {
            Image(systemName: "list.bullet")
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .buttonStyle(.bouncePill)
        .modifier(SevinoGlass.navCircleClear)
        .contentShape(.rect)
        .frame(minWidth: 44 * scale, minHeight: 44 * scale)
        .accessibilityLabel(L10n.Home.menuAccessibility)
    }

    @ViewBuilder
    private var expandedCard: some View {
        Group {
            if viewModel.isLoading, viewModel.holdings.isEmpty {
                loadingContent
            } else if viewModel.error != nil, viewModel.holdings.isEmpty {
                errorContent
            } else {
                HoldingsCardContent(
                    data: HoldingsCardData(
                        holdings: viewModel.holdings,
                        displayOption: viewModel.displayOption.label
                    ),
                    scale: scale,
                    onFilterTapped: toggleFilter
                )
                .transition(.asymmetric(
                    insertion: .opacity.animation(.easeIn(duration: 0.25).delay(0.15)),
                    removal: .identity
                ))
            }
        }
        .modifier(HoldingsCardShell(scale: scale))
    }

    private var loadingContent: some View {
        ProgressView()
            .frame(maxWidth: .infinity)
            .padding(.vertical, 32 * scale)
    }

    private var errorContent: some View {
        ContentUnavailableView {
            Label(L10n.Home.holdingsLoadErrorTitle, systemImage: "exclamationmark.triangle")
        } description: {
            Text(L10n.Home.holdingsLoadErrorMessage)
        } actions: {
            Button(L10n.Home.holdingsLoadErrorRetry, action: retry)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 10 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 20 * scale))
        }
        .frame(maxWidth: .infinity)
    }

    private func toggleFilter() {
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            showFilter.toggle()
        }
    }

    private func retry() {
        Task { await viewModel.loadHoldings() }
    }
}

private struct HoldingsMorphingPreview: View {
    @State private var viewModel = HoldingsViewModel()

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()
            HoldingsMorphingView(
                scale: 1,
                isExpanded: true,
                isHidden: false,
                viewModel: viewModel,
                showFilter: .constant(false),
                onTap: {},
                onDismiss: {}
            )
            .padding(16)
        }
    }
}

#Preview("Dark") {
    HoldingsMorphingPreview()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    HoldingsMorphingPreview()
        .preferredColorScheme(.light)
}
