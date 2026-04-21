import SwiftUI

struct WelcomeView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var currentPage: WelcomePageKind = .portfolio
    @State private var scale: CGFloat = 1

    let onLogIn: () -> Void
    let onSignUp: () -> Void

    init(onLogIn: @escaping () -> Void = {}, onSignUp: @escaping () -> Void = {}) {
        self.onLogIn = onLogIn
        self.onSignUp = onSignUp
    }

    private let pages: [WelcomePage] = [
        WelcomePage(
            kind: .portfolio,
            title: L10n.Welcome.page1Title,
            subtitle: L10n.Welcome.page1Subtitle,
            backgroundImage: "welcome_bg_1"
        ),
        WelcomePage(
            kind: .trade,
            title: L10n.Welcome.page2Title,
            subtitle: L10n.Welcome.page2Subtitle,
            backgroundImage: "welcome_bg_2"
        ),
        WelcomePage(
            kind: .research,
            title: L10n.Welcome.page3Title,
            subtitle: L10n.Welcome.page3Subtitle,
            backgroundImage: "welcome_bg_3"
        ),
        WelcomePage(
            kind: .protected,
            title: L10n.Welcome.page4Title,
            subtitle: L10n.Welcome.page4Subtitle,
            backgroundImage: "welcome_bg_4"
        ),
    ]

    var body: some View {
        VStack(spacing: 0) {
            Image("logo_white")
                .resizable()
                .scaledToFit()
                .frame(height: 44 * scale)
                .padding(.top, 8 * scale)
                .accessibilityLabel(L10n.General.appName)

            TabView(selection: $currentPage) {
                ForEach(pages) { page in
                    WelcomePageContent(page: page, scale: scale)
                        .tag(page.kind)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))

            WelcomePageIndicator(
                pages: pages,
                currentPage: currentPage,
                scale: scale
            )

            WelcomeActionButtons(
                scale: scale,
                onLogIn: onLogIn,
                onSignUp: onSignUp
            )
        }
        .background {
            ZStack {
                ForEach(pages) { page in
                    Image(page.backgroundImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .opacity(currentPage == page.kind ? 1 : 0)
                        .animation(reduceMotion ? nil : .easeInOut(duration: 0.8), value: currentPage)
                        .accessibilityHidden(true)
                }

                LinearGradient(
                    stops: [
                        .init(color: .welcomeOverlayTop, location: 0),
                        .init(color: .welcomeOverlayMid, location: 0.45),
                        .init(color: .welcomeOverlayBottom, location: 1),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
            .ignoresSafeArea()
        }
        .preferredColorScheme(.dark)
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    scale = geo.size.width / 393
                }
            }
        }
        .task {
            await autoAdvancePages()
        }
    }

    private func autoAdvancePages() async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(5))
            guard !Task.isCancelled else { return }
            let allKinds = WelcomePageKind.allCases
            guard let idx = allKinds.firstIndex(of: currentPage) else { return }
            let next = allKinds[(idx + 1) % allKinds.count]
            if reduceMotion {
                currentPage = next
            } else {
                withAnimation(.easeInOut(duration: 0.8)) {
                    currentPage = next
                }
            }
        }
    }
}

// MARK: - Page indicator

private struct WelcomePageIndicator: View {
    let pages: [WelcomePage]
    let currentPage: WelcomePageKind
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            ForEach(pages) { page in
                Circle()
                    .fill(currentPage == page.kind ? Color.welcomeDotActive : Color.welcomeDotInactive)
                    .frame(width: 8 * scale, height: 8 * scale)
                    .animation(.easeInOut(duration: 0.3), value: currentPage)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, 20 * scale)
    }
}

// MARK: - Action buttons

private struct WelcomeActionButtons: View {
    let scale: CGFloat
    let onLogIn: () -> Void
    let onSignUp: () -> Void

    var body: some View {
        HStack(spacing: 16 * scale) {
            actionButton(L10n.Welcome.logIn, tint: .welcomeButtonDarkTint, textColor: .welcomeText, action: onLogIn)
            actionButton(L10n.Welcome.signUp, tint: .welcomeButtonLightTint, textColor: .welcomeButtonDarkTint, action: onSignUp)
        }
        .padding(.horizontal, 24 * scale)
        .padding(.bottom, 16 * scale)
    }

    private func actionButton(
        _ title: String,
        tint: Color,
        textColor: Color,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(textColor)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(tint: tint))
    }
}

#Preview {
    WelcomeView()
}
