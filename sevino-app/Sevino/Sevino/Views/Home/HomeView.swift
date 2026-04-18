import SwiftUI

struct HomeView: View {
    @State private var viewModel = HomeViewModel()
    @State private var messageText = ""
    @State private var scale: CGFloat = 1
    @State private var showExplore = true

    var body: some View {
        SevinoGlassContainer {
            ZStack {
                GreetingSection(
                    scale: scale,
                    greeting: viewModel.greeting,
                    showExplore: $showExplore
                )
                .offset(y: -60 * scale)

                VStack(spacing: 0) {
                    HStack {
                        navSidebarButton
                        navPortfolioPill

                        Spacer()

                        HStack(spacing: 8 * scale) {
                            navCircleButton(icon: "dollarsign", label: L10n.Home.fundingAccessibility)
                            navCircleButton(icon: "eye", label: L10n.Home.watchlistAccessibility)
                            navCircleButton(icon: "list.bullet", label: L10n.Home.menuAccessibility)
                        }
                    }
                    .padding(.horizontal, 16 * scale)
                    .padding(.top, 4 * scale)

                    Spacer()

                    ChatSuggestions(scale: scale, onSelect: { messageText = $0 })
                        .padding(.bottom, 20 * scale)
                        .padding(.horizontal, 16 * scale)

                    ChatInputBar(text: $messageText, scale: scale)
                        .padding(.horizontal, 16 * scale)
                        .padding(.bottom, 8 * scale)
                }
            }
        }
        .background { HomeBackgroundView() }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    scale = geo.size.width / 393
                }
            }
        }
        .task { viewModel.loadGreeting() }
    }

    private var navSidebarButton: some View {
        Button(action: {}) {
            Image(systemName: "sidebar.left")
                .font(.system(size: 16 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .modifier(SevinoGlass.navCircle)
        .accessibilityLabel(L10n.Home.sidebarAccessibility)
    }

    private var navPortfolioPill: some View {
        Button(action: {}) {
            HStack(spacing: 8 * scale) {
                Text(viewModel.portfolioDisplayValue)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)

                VStack(spacing: -2 * scale) {
                    Image(systemName: "chevron.down")
                    Image(systemName: "chevron.down")
                }
                .font(.system(size: 9 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoNegative)
                .accessibilityHidden(true)
            }
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 8 * scale)
        }
        .modifier(SevinoGlass.chip)
        .accessibilityLabel(L10n.Home.portfolioAccessibility)
    }

    private func navCircleButton(icon: String, label: String) -> some View {
        Button(action: {}) {
            Image(systemName: icon)
                .font(.system(size: 16 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .modifier(SevinoGlass.navCircle)
        .accessibilityLabel(label)
    }
}

private struct GreetingSection: View {
    @Environment(\.colorScheme) private var colorScheme
    let scale: CGFloat
    let greeting: String
    @Binding var showExplore: Bool

    var body: some View {
        VStack(spacing: 16 * scale) {
            Image(colorScheme == .dark ? "logo_white" : "logo_black")
                .resizable()
                .scaledToFit()
                .frame(height: 40 * scale)
                .accessibilityLabel(L10n.General.appName)

            Text(greeting)
                .font(.system(size: 28 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)

            if showExplore {
                HStack(spacing: 8 * scale) {
                    Button(L10n.Home.exploreButton, action: {})
                        .font(.system(size: 15 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Button(L10n.Home.dismissExploreAccessibility, systemImage: "xmark", action: dismissExplore)
                        .labelStyle(.iconOnly)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 10 * scale)
                .modifier(SevinoGlass.chip)
            }
        }
    }

    private func dismissExplore() {
        withAnimation { showExplore = false }
    }
}

private struct ChatSuggestions: View {
    let scale: CGFloat
    let onSelect: (String) -> Void

    private let suggestions = [
        L10n.Home.suggestionNews,
        L10n.Home.suggestionPortfolio,
        L10n.Home.suggestionRadar,
    ]

    var body: some View {
        VStack(alignment: .trailing, spacing: 14 * scale) {
            ForEach(Array(suggestions.enumerated()), id: \.offset) { _, suggestion in
                Button { onSelect(stripped(suggestion)) } label: {
                    HStack(spacing: 6 * scale) {
                        Text(suggestion)
                            .font(.system(size: 14 * scale))
                            .foregroundStyle(Color.homeSendActiveBg)

                        Image(systemName: "arrow.down.left")
                            .font(.system(size: 11 * scale, weight: .semibold))
                            .foregroundStyle(Color.homeSendActiveBg)
                            .accessibilityHidden(true)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }

    private func stripped(_ text: String) -> String {
        text.trimmingCharacters(in: CharacterSet(charactersIn: "\u{201C}\u{201D}\""))
    }
}

private struct ChatInputBar: View {
    @Binding var text: String
    let scale: CGFloat
    @FocusState private var isFocused: Bool

    private var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            TextField(L10n.Home.chatPlaceholder, text: $text, axis: .vertical)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .lineLimit(1...5)
                .focused($isFocused)
                .padding(.horizontal, 16 * scale)
                .padding(.top, 14 * scale)
                .padding(.bottom, 8 * scale)

            HStack(spacing: 0) {
                Button(L10n.Home.attachAccessibility, systemImage: "plus", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Spacer()

                Button(L10n.Home.micAccessibility, systemImage: "mic", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Button(L10n.Home.sendAccessibility, systemImage: "arrow.up", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(hasText ? Color.sevinoPrimary : Color.sevinoGreyAccent)
                    .frame(width: 30 * scale, height: 30 * scale)
                    .background(hasText ? Color.homeSendActiveBg : .clear, in: .circle)
                    .frame(width: 44 * scale, height: 44 * scale)
            }
            .padding(.horizontal, 4 * scale)
            .padding(.bottom, 4 * scale)
        }
        .modifier(SevinoGlass.card)
    }
}

#Preview("Dark") {
    HomeView()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    HomeView()
        .preferredColorScheme(.light)
}
