import SwiftUI

struct HomeView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.textSizeMultiplier) private var textSizeMultiplier
    @State private var viewModel = HomeViewModel()
    @State private var portfolioViewModel = PortfolioViewModel()
    @State private var fundingViewModel = FundingViewModel()
    @State private var holdingsViewModel = HoldingsViewModel()
    @State private var radarViewModel = RadarViewModel()
    @State private var messageText = ""
    @State private var baseScale: CGFloat = 1
    private var scale: CGFloat { baseScale * textSizeMultiplier }
    @State private var showExplore = true
    @State private var showPortfolio = false
    @State private var showFunding = false
    @State private var showHoldings = false
    @State private var showHoldingsFilter = false
    @State private var showRadar = false
    @State private var showSidebar = false

    private var anyModalOpen: Bool { showPortfolio || showFunding || showHoldings || showRadar }

    var body: some View {
        ZStack {
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
                            Color.clear.frame(width: 120 * scale, height: 36 * scale)
                            Spacer()
                            HStack(spacing: 8 * scale) {
                                Color.clear.frame(width: 36 * scale, height: 36 * scale)
                                Color.clear.frame(width: 36 * scale, height: 36 * scale)
                                Color.clear.frame(width: 36 * scale, height: 36 * scale)
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
            .blur(radius: anyModalOpen ? 10 : 0)
            .brightness(anyModalOpen && colorScheme == .light ? -0.3 : 0)
            .allowsHitTesting(!anyModalOpen)

            Color.sevinoPrimary
                .opacity(anyModalOpen ? 0.4 : 0)
                .ignoresSafeArea()
                .onTapGesture {
                    if showHoldingsFilter {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) { showHoldingsFilter = false }
                    } else {
                        dismissAllModals()
                    }
                }
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(L10n.Home.dismissAccessibility)
                .allowsHitTesting(anyModalOpen)

            PortfolioMorphingView(
                scale: scale,
                isExpanded: showPortfolio,
                viewModel: portfolioViewModel,
                onTap: togglePortfolio,
                onDismiss: dismissPortfolio
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(.leading, showPortfolio ? 16 * scale : (16 + 36 + 8) * scale)
            .padding(.trailing, showPortfolio ? 16 * scale : 0)
            .padding(.top, 4 * scale)
            .ignoresSafeArea(.keyboard)
            .allowsHitTesting(!showFunding && !showHoldings && !showRadar)
            .opacity(showFunding || showHoldings || showRadar ? 0 : 1)

            FundingMorphingView(
                scale: scale,
                isExpanded: showFunding,
                viewModel: fundingViewModel,
                onTap: toggleFunding,
                onDismiss: dismissFunding
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            .padding(.trailing, showFunding ? 16 * scale : (16 + 36 + 8 + 36 + 8) * scale)
            .padding(.leading, showFunding ? 16 * scale : 0)
            .padding(.top, 4 * scale)
            .ignoresSafeArea(.keyboard)
            .allowsHitTesting(!showPortfolio && !showHoldings && !showRadar)
            .opacity(showPortfolio || showHoldings || showRadar ? 0 : 1)

            HoldingsMorphingView(
                scale: scale,
                isExpanded: showHoldings,
                viewModel: holdingsViewModel,
                showFilter: $showHoldingsFilter,
                onTap: toggleHoldings,
                onDismiss: dismissHoldings
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            .padding(.trailing, showHoldings ? 16 * scale : 16 * scale)
            .padding(.leading, showHoldings ? 16 * scale : 0)
            .padding(.top, 4 * scale)
            .ignoresSafeArea(.keyboard)
            .allowsHitTesting(!showPortfolio && !showFunding && !showRadar)
            .opacity(showPortfolio || showFunding || showRadar ? 0 : 1)

            RadarMorphingView(
                scale: scale,
                isExpanded: showRadar,
                viewModel: radarViewModel,
                onTap: toggleRadar,
                onDismiss: dismissRadar
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            .padding(.trailing, showRadar ? 16 * scale : (16 + 36 + 8) * scale)
            .padding(.leading, showRadar ? 16 * scale : 0)
            .padding(.top, 4 * scale)
            .ignoresSafeArea(.keyboard)
            .allowsHitTesting(!showPortfolio && !showFunding && !showHoldings)
            .opacity(showPortfolio || showFunding || showHoldings ? 0 : 1)
        }
        .background { HomeBackgroundView() }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    baseScale = geo.size.width / 393
                }
            }
        }
        .mask {
            RoundedRectangle(cornerRadius: showSidebar ? 28 * scale : 0)
                .ignoresSafeArea()
        }
        .overlay {
            Color.clear
                .contentShape(.rect)
                .ignoresSafeArea()
                .onTapGesture { toggleSidebar() }
                .allowsHitTesting(showSidebar)
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(L10n.Home.dismissAccessibility)
        }
        .offset(x: showSidebar ? 300 * scale : 0)
        .background {
            SidebarPanelView(
                scale: scale,
                chats: viewModel.chats,
                founderPhoneURL: viewModel.founderPhoneURL(),
                founderTextURL: viewModel.founderTextURL(),
                contactEmailURL: viewModel.contactEmailURL()
            )
        }
        .task { await viewModel.load() }
        .task { await fundingViewModel.loadFundingData() }
        .task { await holdingsViewModel.loadHoldings() }
        .task { await radarViewModel.loadRadar() }
        .task(id: portfolioViewModel.selectedTimeRange) {
            await portfolioViewModel.loadPortfolio()
        }
        .alert(
            L10n.Home.portfolioLoadErrorTitle,
            isPresented: Binding(
                get: { portfolioViewModel.error != nil },
                set: { if !$0 { portfolioViewModel.clearError() } }
            ),
            presenting: portfolioViewModel.error
        ) { _ in
            Button(L10n.Home.portfolioLoadErrorRetry) {
                Task { await portfolioViewModel.loadPortfolio() }
            }
            Button(L10n.Home.portfolioLoadErrorDismiss, role: .cancel) {
                portfolioViewModel.clearError()
            }
        } message: { message in
            Text(message)
        }
        .alert(
            L10n.Home.fundingLoadErrorTitle,
            isPresented: Binding(
                get: { fundingViewModel.error != nil },
                set: { if !$0 { fundingViewModel.clearError() } }
            ),
            presenting: fundingViewModel.error
        ) { _ in
            Button(L10n.Home.fundingLoadErrorRetry) {
                Task { await fundingViewModel.loadFundingData() }
            }
            Button(L10n.Home.fundingLoadErrorDismiss, role: .cancel) {
                fundingViewModel.clearError()
            }
        } message: { message in
            Text(message)
        }
        .alert(
            L10n.Home.radarLoadErrorTitle,
            isPresented: Binding(
                get: { radarViewModel.error != nil },
                set: { if !$0 { radarViewModel.clearError() } }
            ),
            presenting: radarViewModel.error
        ) { _ in
            Button(L10n.Home.radarLoadErrorRetry) {
                Task { await radarViewModel.loadRadar() }
            }
            Button(L10n.Home.radarLoadErrorDismiss, role: .cancel) {
                radarViewModel.clearError()
            }
        } message: { message in
            Text(message)
        }
        .alert(
            L10n.Home.homeLoadErrorTitle,
            isPresented: Binding(
                get: { viewModel.error != nil },
                set: { if !$0 { viewModel.clearError() } }
            ),
            presenting: viewModel.error
        ) { _ in
            Button(L10n.Home.homeLoadErrorRetry) {
                Task { await viewModel.load() }
            }
            Button(L10n.Home.homeLoadErrorDismiss, role: .cancel) {
                viewModel.clearError()
            }
        } message: { message in
            Text(message)
        }
    }

    private func togglePortfolio() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showPortfolio.toggle()
        }
    }

    private func dismissPortfolio() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showPortfolio = false
        }
    }

    private func toggleFunding() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showFunding.toggle()
        }
    }

    private func dismissFunding() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showFunding = false
        }
    }

    private func toggleHoldings() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showHoldings.toggle()
        }
    }

    private func dismissHoldings() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showHoldings = false
        }
    }

    private func toggleRadar() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showRadar.toggle()
        }
    }

    private func dismissRadar() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showRadar = false
        }
    }

    private func dismissAllModals() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showPortfolio = false
            showFunding = false
            showHoldings = false
            showRadar = false
        }
    }

    private func toggleSidebar() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showSidebar.toggle()
        }
    }

    private var navSidebarButton: some View {
        Button(action: toggleSidebar) {
            Image(systemName: "sidebar.left")
                .font(.system(size: 16 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .modifier(SevinoGlass.navCircle)
        .accessibilityLabel(L10n.Home.sidebarAccessibility)
    }

}

private struct SidebarPanelView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL

    let scale: CGFloat
    let chats: [ChatItem]
    let founderPhoneURL: URL?
    let founderTextURL: URL?
    let contactEmailURL: URL?

    @State private var searchText = ""
    @State private var showContactOptions = false
    @State private var showFounderContact = false
    @State private var showSettings = false

    var body: some View {
        ZStack {
            Color.sevinoSettingsBg
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Image(colorScheme == .dark ? "logo_white" : "logo_black")
                        .resizable()
                        .scaledToFit()
                        .frame(height: 36 * scale)
                        .accessibilityLabel(L10n.General.appName)

                    Spacer()

                    chatButton
                }
                .padding(.bottom, 20 * scale)

                HStack {
                    TextField(L10n.Sidebar.searchPlaceholder, text: $searchText)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 16 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.horizontal, 14 * scale)
                .padding(.vertical, 12 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.3), in: .capsule)
                .padding(.bottom, 20 * scale)

                Text(L10n.Sidebar.chatsHeader)
                    .font(.system(size: 14 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .padding(.bottom, 6 * scale)

                ForEach(chats) { chat in
                    Button(action: {}) {
                        Text(chat.title)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.sevinoSecondary)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 11 * scale)
                            .padding(.horizontal, 12 * scale)
                            .background(
                                chat.id == chats.first?.id
                                    ? Color.sevinoGreyAccent.opacity(0.3)
                                    : .clear,
                                in: .rect(cornerRadius: 8 * scale)
                            )
                    }
                    .disabled(true)
                }

                Spacer()

                HStack {
                    Button(action: { showSettings = true }) {
                        HStack(spacing: 6 * scale) {
                            Text(L10n.Sidebar.userName)
                                .font(.system(size: 15 * scale, weight: .medium))
                                .foregroundStyle(Color.sevinoSecondary)

                            Image(systemName: "chevron.down")
                                .font(.system(size: 11 * scale, weight: .semibold))
                                .foregroundStyle(Color.sevinoSecondary)
                                .accessibilityHidden(true)
                        }
                        .padding(.horizontal, 16 * scale)
                        .padding(.vertical, 10 * scale)
                    }
                    .modifier(SevinoGlass.chip)
                    .fullScreenCover(isPresented: $showSettings) {
                        SettingsView()
                    }

                    Spacer()

                    Button(L10n.Sidebar.newChatAccessibility, systemImage: "plus.circle", action: {})
                        .labelStyle(.iconOnly)
                        .font(.system(size: 24 * scale, weight: .light))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(width: 44 * scale, height: 44 * scale)
                        .modifier(SevinoGlass.navCircle)
                        .disabled(true)
                }
                .padding(.bottom, 8 * scale)
            }
            .padding(.horizontal, 14 * scale)
            .padding(.top, 16 * scale)
            .frame(width: 300 * scale, alignment: .leading)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }

    private var chatButton: some View {
        Button(L10n.Sidebar.chatAccessibility, systemImage: "message", action: { showContactOptions = true })
            .labelStyle(.iconOnly)
            .font(.system(size: 16 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: 44 * scale, height: 44 * scale)
            .modifier(SevinoGlass.navCircle)
            .confirmationDialog(L10n.Sidebar.contactTitle, isPresented: $showContactOptions) {
                Button(L10n.Sidebar.talkToFounders, action: { showFounderContact = true })
                Button(L10n.Sidebar.contactUs, action: openEmail)
            }
            .confirmationDialog(L10n.Sidebar.talkToFounders, isPresented: $showFounderContact) {
                Button(L10n.Sidebar.callFounders, action: callFounders)
                Button(L10n.Sidebar.textFounders, action: textFounders)
            }
    }

    private func callFounders() {
        guard let url = founderPhoneURL else { return }
        openURL(url)
    }

    private func textFounders() {
        guard let url = founderTextURL else { return }
        openURL(url)
    }

    private func openEmail() {
        guard let url = contactEmailURL else { return }
        openURL(url)
    }
}

/// A single view that morphs between the small portfolio pill and the expanded modal.
private struct PortfolioMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let viewModel: PortfolioViewModel
    let onTap: () -> Void
    let onDismiss: () -> Void

    var body: some View {
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
        .gesture(isExpanded ? nil : TapGesture().onEnded { onTap() })
        .accessibilityAddTraits(.isButton)
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

/// The expanded-only content (gain text, chart, time selector, chat button).
private struct PortfolioExpandedContent: View {
    let scale: CGFloat
    let viewModel: PortfolioViewModel
    @State private var scrubValue: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            Text("\(viewModel.gainText) \(viewModel.periodLabel)")
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoPositive)

            PortfolioChartView(points: viewModel.chartPoints, scale: scale, scrubValue: $scrubValue)
                .frame(height: 160 * scale)

            TimeRangeSelector(
                selected: viewModel.selectedTimeRange,
                scale: scale,
                onSelect: viewModel.setTimeRange
            )

            Button(L10n.Home.chatAboutThis, action: {})
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 12 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 24 * scale))
        }
        .transition(.opacity.animation(.easeIn(duration: 0.25).delay(0.15)))
    }
}

private struct TimeRangeSelector: View {
    let selected: TimeRange
    let scale: CGFloat
    let onSelect: (TimeRange) -> Void

    @Namespace private var indicator
    @GestureState private var dragLocation: CGFloat?
    @State private var totalWidth: CGFloat = 0

    private var isDragging: Bool { dragLocation != nil }

    var body: some View {
        HStack(spacing: 0) {
            ForEach(TimeRange.allCases) { range in
                Text(range.rawValue)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(
                        range == activeRange
                            ? Color.sevinoSecondary
                            : Color.sevinoGreyContrast
                    )
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6 * scale)
                    .background {
                        if range == activeRange {
                            Capsule()
                                .fill(.clear)
                                .modifier(SevinoGlass.chip)
                                .scaleEffect(isDragging ? 1.25 : 1.0)
                                .matchedGeometryEffect(id: "timeIndicator", in: indicator)
                        }
                    }
                    .contentShape(.rect)
                    .onTapGesture {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                            onSelect(range)
                        }
                    }
                    .accessibilityAddTraits(.isButton)
            }
        }
        .onGeometryChange(for: CGFloat.self) { geo in
            geo.size.width
        } action: { newValue in
            totalWidth = newValue
        }
        .gesture(
            DragGesture(minimumDistance: 0)
                .updating($dragLocation) { value, state, _ in
                    state = value.location.x
                }
                .onEnded { value in
                    if let range = rangeAt(x: value.location.x) {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                            onSelect(range)
                        }
                    }
                }
        )
        .animation(.spring(duration: 0.3, bounce: 0.15), value: activeRange)
        .animation(.spring(duration: 0.25, bounce: 0.2), value: isDragging)
    }

    private var activeRange: TimeRange {
        if let x = dragLocation, let range = rangeAt(x: x) {
            return range
        }
        return selected
    }

    private func rangeAt(x: CGFloat) -> TimeRange? {
        let cases = TimeRange.allCases
        guard !cases.isEmpty, totalWidth > 0 else { return nil }
        let itemWidth = totalWidth / CGFloat(cases.count)
        let idx = Int(x / itemWidth)
        guard idx >= 0, idx < cases.count else { return nil }
        return cases[idx]
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
