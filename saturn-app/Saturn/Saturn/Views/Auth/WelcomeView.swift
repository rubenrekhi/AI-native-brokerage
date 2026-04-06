import SwiftUI

// MARK: - Data models

private enum WelcomePageKind: CaseIterable, Identifiable {
    case portfolio, trade, research, protected

    var id: Self { self }
}

private struct WelcomePage: Identifiable {
    var id: WelcomePageKind { kind }
    let kind: WelcomePageKind
    let title: String
    let subtitle: String
    let backgroundImage: String
}

private enum Timeframe: String, CaseIterable, Identifiable {
    case oneDay = "1D"
    case oneWeek = "1W"
    case oneMonth = "1M"
    case threeMonths = "3M"
    case sixMonths = "6M"
    case ytd = "YTD"
    case oneYear = "1Y"
    case all = "ALL"

    var id: String { rawValue }
}

// MARK: - WelcomeView

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
        .task(id: currentPage) {
            await advancePage()
        }
    }

    private func advancePage() async {
        try? await Task.sleep(for: .seconds(5))
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

// MARK: - Page content

private struct WelcomePageContent: View {
    let page: WelcomePage
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 0) {
            Text(page.title)
                .font(.dmSerif(size: 36 * scale))
                .foregroundStyle(Color.welcomeText)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 20 * scale)
                .padding(.bottom, 12 * scale)

            Text(page.subtitle)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeTextSecondary)
                .multilineTextAlignment(.center)
                .lineSpacing(3 * scale)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)

            switch page.kind {
            case .portfolio: PortfolioCardView(scale: scale)
            case .trade: TradeCardView(scale: scale)
            case .research: ResearchCardView(scale: scale)
            case .protected: ProtectedCardView(scale: scale)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Animated chart line

private struct AnimatedChartLine: View {
    let points: [CGFloat]
    let scale: CGFloat
    let height: CGFloat
    let progress: CGFloat

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height

            Path { path in
                for (i, point) in points.enumerated() {
                    let x = w * CGFloat(i) / CGFloat(points.count - 1)
                    let y = h * (1 - point)
                    if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                    else { path.addLine(to: CGPoint(x: x, y: y)) }
                }
                path.addLine(to: CGPoint(x: w, y: h))
                path.addLine(to: CGPoint(x: 0, y: h))
                path.closeSubpath()
            }
            .fill(
                LinearGradient(
                    colors: [Color.welcomeChart.opacity(0.3), Color.welcomeChart.opacity(0)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .mask(alignment: .leading) {
                Rectangle()
                    .frame(width: w * progress)
            }

            Path { path in
                for (i, point) in points.enumerated() {
                    let x = w * CGFloat(i) / CGFloat(points.count - 1)
                    let y = h * (1 - point)
                    if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                    else { path.addLine(to: CGPoint(x: x, y: y)) }
                }
            }
            .trim(from: 0, to: progress)
            .stroke(Color.welcomeChart, lineWidth: 1.5)
        }
        .frame(height: height * scale)
    }
}

// MARK: - Timeframe tabs

private struct TimeframeTabsView: View {
    let scale: CGFloat
    let selected: Timeframe

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Timeframe.allCases) { tf in
                let isSelected = tf == selected
                Text(tf.rawValue)
                    .font(.system(size: 11 * scale, weight: isSelected ? .bold : .regular))
                    .foregroundStyle(isSelected ? Color.welcomeText : Color.welcomeTextDimmed)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6 * scale)
                    .background {
                        if isSelected {
                            Capsule()
                                .fill(Color.welcomeTabHighlight)
                        }
                    }
            }
        }
    }
}

// MARK: - Portfolio card (slide 1)

private struct PortfolioCardView: View {
    let scale: CGFloat
    @State private var chartProgress: CGFloat = 0

    private static let chartPoints: [CGFloat] = [
        0.45, 0.42, 0.40, 0.38, 0.35, 0.33, 0.30, 0.32, 0.28, 0.25,
        0.27, 0.30, 0.28, 0.32, 0.35, 0.33, 0.36, 0.40, 0.38, 0.42,
        0.45, 0.50, 0.55, 0.52, 0.58, 0.55, 0.60, 0.65, 0.70, 0.68,
        0.72, 0.78, 0.82, 0.85, 0.80, 0.88, 0.92, 0.95, 0.90, 0.98,
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.Welcome.portfolioLabel)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.welcomeTextMuted)

            HStack(alignment: .firstTextBaseline, spacing: 8 * scale) {
                Text(L10n.Welcome.portfolioValue)
                    .font(.system(size: 28 * scale, weight: .bold))
                    .foregroundStyle(Color.welcomeText)

                Text(L10n.Welcome.portfolioGain)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.saturnPositive)
            }
            .padding(.top, 4 * scale)

            AnimatedChartLine(
                points: Self.chartPoints,
                scale: scale,
                height: 80,
                progress: chartProgress
            )
            .padding(.top, 12 * scale)

            TimeframeTabsView(scale: scale, selected: .threeMonths)
                .padding(.top, 12 * scale)
        }
        .padding(16 * scale)
        .modifier(SaturnGlass.card)
        .onAppear { animateChart() }
    }

    private func animateChart() {
        chartProgress = 0
        withAnimation(.easeOut(duration: 1.5)) {
            chartProgress = 1
        }
    }
}

// MARK: - Trade card (slide 2)

private struct TradeCardView: View {
    let scale: CGFloat

    var body: some View {
        SaturnGlassContainer {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Spacer()
                    Text(L10n.Welcome.tradeUserMessage)
                        .font(.system(size: 14 * scale))
                        .foregroundStyle(Color.welcomeTextSecondary)
                        .padding(.horizontal, 16 * scale)
                        .padding(.vertical, 10 * scale)
                        .background(
                            Color.welcomeButtonDarkTint,
                            in: RoundedRectangle(cornerRadius: 16 * scale)
                        )
                }
                .padding(.bottom, 12 * scale)

                Text(L10n.Welcome.tradeAIResponse)
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.welcomeText)
                    .lineSpacing(3 * scale)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 12 * scale)

                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 10 * scale) {
                        Image(decorative: "amd_logo")
                            .resizable()
                            .scaledToFill()
                            .frame(width: 40 * scale, height: 40 * scale)
                            .clipShape(RoundedRectangle(cornerRadius: 8 * scale))

                        VStack(alignment: .leading, spacing: 2 * scale) {
                            Text(L10n.Welcome.tradeStockName)
                                .font(.system(size: 14 * scale, weight: .semibold))
                                .foregroundStyle(Color.welcomeText)
                            Text(L10n.Welcome.tradeStockTicker)
                                .font(.system(size: 12 * scale))
                                .foregroundStyle(Color.welcomeTextDimmed)
                        }
                    }
                    .padding(.bottom, 12 * scale)

                    HStack {
                        Text(L10n.Welcome.tradeEstimatedTotal)
                            .font(.system(size: 14 * scale))
                            .foregroundStyle(Color.welcomeTextDimmed)
                        Spacer()
                        Text(L10n.Welcome.tradeEstimatedValue)
                            .font(.system(size: 20 * scale, weight: .bold))
                            .foregroundStyle(Color.welcomeText)
                    }
                    .padding(.bottom, 14 * scale)

                    Text(L10n.Welcome.tradeHoldToConfirm)
                        .font(.system(size: 14 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeText)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12 * scale)
                        .background(Color.saturnPositive, in: Capsule())
                }
                .padding(12 * scale)
                .modifier(SaturnGlass.card)
            }
            .padding(16 * scale)
            .modifier(SaturnGlass.card)
        }
    }
}

// MARK: - Research card (slide 3)

private struct ResearchCardView: View {
    let scale: CGFloat
    @State private var cursorVisible = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                Text(L10n.Welcome.researchQuery)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeText)

                Rectangle()
                    .fill(Color.welcomeText)
                    .frame(width: 2 * scale, height: 20 * scale)
                    .opacity(cursorVisible ? 1 : 0)
                    .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: cursorVisible)
                    .onAppear { cursorVisible = false }
            }
            .padding(.horizontal, 12 * scale)
            .padding(.top, 12 * scale)
            .padding(.bottom, 14 * scale)

            HStack(spacing: 0) {
                Image(systemName: "plus")
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(width: 36 * scale, height: 36 * scale)
                    .accessibilityHidden(true)

                Spacer()

                Image(systemName: "mic.fill")
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(width: 36 * scale, height: 36 * scale)
                    .accessibilityHidden(true)

                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28 * scale))
                    .foregroundStyle(Color.welcomeTextSecondary)
                    .frame(width: 36 * scale, height: 36 * scale)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 6 * scale)
            .padding(.vertical, 6 * scale)
        }
        .padding(.horizontal, 4 * scale)
        .modifier(SaturnGlass.card)
    }
}

// MARK: - Protected card (slide 4)

private struct ProtectedCardView: View {
    let scale: CGFloat
    @State private var chartProgress: CGFloat = 0

    private static let chartPoints: [CGFloat] = [
        0.20, 0.18, 0.19, 0.17, 0.15, 0.16, 0.14, 0.15, 0.13, 0.12,
        0.14, 0.13, 0.15, 0.14, 0.16, 0.15, 0.17, 0.18, 0.16, 0.19,
        0.20, 0.22, 0.21, 0.24, 0.23, 0.25, 0.28, 0.30, 0.32, 0.35,
        0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.75, 0.80, 0.88, 0.95,
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.Welcome.portfolioLabel)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.welcomeTextMuted)

            HStack(alignment: .firstTextBaseline, spacing: 8 * scale) {
                Text(L10n.Welcome.protectedValue)
                    .font(.system(size: 28 * scale, weight: .bold))
                    .foregroundStyle(Color.welcomeText)

                Image(systemName: "lock.fill")
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .accessibilityHidden(true)
            }
            .padding(.top, 4 * scale)

            AnimatedChartLine(
                points: Self.chartPoints,
                scale: scale,
                height: 100,
                progress: chartProgress
            )
            .padding(.top, 12 * scale)
        }
        .padding(16 * scale)
        .modifier(SaturnGlass.card)
        .onAppear { animateChart() }
    }

    private func animateChart() {
        chartProgress = 0
        withAnimation(.easeOut(duration: 1.5)) {
            chartProgress = 1
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
        .modifier(SaturnGlass.tintedButton(tint: tint))
    }
}

#Preview {
    WelcomeView()
}
