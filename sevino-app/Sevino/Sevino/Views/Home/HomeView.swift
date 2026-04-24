import SwiftUI

struct HomeView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.textSizeMultiplier) private var textSizeMultiplier
    @State private var viewModel: HomeViewModel
    @State private var portfolioViewModel: PortfolioViewModel
    @State private var fundingViewModel: FundingViewModel
    @State private var holdingsViewModel: HoldingsViewModel
    @State private var radarViewModel: RadarViewModel
    @State private var transferViewModel: TransferViewModel
    @State private var tickerMentionViewModel = TickerMentionViewModel()
    @State private var chatInputHeight: CGFloat = 0
    @State private var baseScale: CGFloat = 1
    private var scale: CGFloat { baseScale * textSizeMultiplier }
    @State private var showExplore = true
    @State private var showPortfolio = false
    @State private var showFunding = false
    @State private var showHoldings = false
    @State private var showHoldingsFilter = false
    @State private var showRadar = false
    @State private var showSidebar = false
    @State private var showQuickCommands = false
    // TODO: wire web search flag to outgoing chat requests (placeholder state)
    @State private var webSearchEnabled = false
    @State private var bottomSafeArea: CGFloat = 0

    private var anyModalOpen: Bool { showPortfolio || showFunding || showHoldings || showRadar }
    private var anyDismissableLayerOpen: Bool { anyModalOpen || showHoldingsFilter || showQuickCommands }

    private func modalDimBrightness(when isDimmed: Bool) -> Double {
        guard isDimmed else { return 0 }
        return colorScheme == .light ? -0.3 : -0.2
    }

    init(
        viewModel: HomeViewModel = HomeViewModel(),
        portfolioViewModel: PortfolioViewModel = PortfolioViewModel(),
        fundingViewModel: FundingViewModel = FundingViewModel(),
        holdingsViewModel: HoldingsViewModel = HoldingsViewModel(),
        radarViewModel: RadarViewModel = RadarViewModel(),
        transferViewModel: TransferViewModel = TransferViewModel()
    ) {
        self._viewModel = State(initialValue: viewModel)
        self._portfolioViewModel = State(initialValue: portfolioViewModel)
        self._fundingViewModel = State(initialValue: fundingViewModel)
        self._holdingsViewModel = State(initialValue: holdingsViewModel)
        self._radarViewModel = State(initialValue: radarViewModel)
        self._transferViewModel = State(initialValue: transferViewModel)
    }

    var body: some View {
        SevinoGlassContainer {
            ZStack {
                HomeGreetingSection(
                    scale: scale,
                    greeting: viewModel.greeting,
                    showExplore: $showExplore,
                    isHidden: anyModalOpen
                )
                .offset(y: -60 * scale)
                .allowsHitTesting(!anyModalOpen)
                .accessibilityHidden(anyModalOpen)
                .blur(radius: anyModalOpen ? 10 : 0)
                .brightness(modalDimBrightness(when: anyModalOpen))

                VStack(spacing: 0) {
                    HStack(spacing: 8 * scale) {
                        if anyModalOpen {
                            Color.clear.frame(width: 44 * scale, height: 44 * scale)
                        } else {
                            navSidebarButton
                        }
                        Color.clear.frame(width: 120 * scale, height: 44 * scale)
                        Spacer()
                        HStack(spacing: 8 * scale) {
                            Color.clear.frame(width: 44 * scale, height: 44 * scale)
                            Color.clear.frame(width: 44 * scale, height: 44 * scale)
                            Color.clear.frame(width: 44 * scale, height: 44 * scale)
                        }
                    }
                    .padding(.horizontal, 16 * scale)
                    .padding(.top, 4 * scale)

                    Spacer()
                }
                .blur(radius: anyModalOpen ? 10 : 0)
                .brightness(modalDimBrightness(when: anyModalOpen))
                .allowsHitTesting(!anyModalOpen)

                Button(action: dismissTopLayer) {
                    Color.sevinoPrimary
                        .opacity(anyModalOpen ? 0.4 : 0)
                        .ignoresSafeArea()
                }
                .buttonStyle(.plain)
                .contentShape(Rectangle())
                .accessibilityLabel(L10n.Home.dismissAccessibility)
                .accessibilityHidden(!anyDismissableLayerOpen)
                .allowsHitTesting(anyDismissableLayerOpen)

                PortfolioMorphingView(
                    scale: scale,
                    isExpanded: showPortfolio,
                    isHidden: showFunding || showHoldings || showRadar,
                    viewModel: portfolioViewModel,
                    onTap: togglePortfolio
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(.leading, showPortfolio ? 16 * scale : (16 + 44 + 4) * scale)
                .padding(.trailing, showPortfolio ? 16 * scale : 0)
                .padding(.top, 4 * scale)
                .ignoresSafeArea(.keyboard)

                FundingMorphingView(
                    scale: scale,
                    isExpanded: showFunding,
                    isHidden: showPortfolio || showHoldings || showRadar,
                    viewModel: fundingViewModel,
                    onTap: toggleFunding,
                    onDismiss: dismissFunding,
                    onDeposit: { startTransfer(.deposit) },
                    onWithdraw: { startTransfer(.withdraw) }
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(.trailing, showFunding ? 16 * scale : (16 + 44 + 44) * scale)
                .padding(.leading, showFunding ? 16 * scale : 0)
                .padding(.top, 4 * scale)
                .ignoresSafeArea(.keyboard)

                HoldingsMorphingView(
                    scale: scale,
                    isExpanded: showHoldings,
                    isHidden: showPortfolio || showFunding || showRadar,
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

                RadarMorphingView(
                    scale: scale,
                    isExpanded: showRadar,
                    isHidden: showPortfolio || showFunding || showHoldings,
                    viewModel: radarViewModel,
                    onTap: toggleRadar,
                    onDismiss: dismissRadar
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(.trailing, showRadar ? 16 * scale : (16 + 44) * scale)
                .padding(.leading, showRadar ? 16 * scale : 0)
                .padding(.top, 4 * scale)
                .ignoresSafeArea(.keyboard)

                tickerPopupDismissButton

                VStack(spacing: 0) {
                    Spacer()

                    HomeChatSuggestions(scale: scale, onSelect: { tickerMentionViewModel.updateText($0) })
                        .padding(.bottom, 20 * scale)
                        .padding(.horizontal, 16 * scale)
                        .blur(radius: anyModalOpen ? 10 : 0)
                        .brightness(modalDimBrightness(when: anyModalOpen))
                        .allowsHitTesting(!anyModalOpen)

                    HomeChatInputBar(
                        viewModel: tickerMentionViewModel,
                        scale: scale,
                        isDimmed: anyModalOpen,
                        onSend: { _ in },
                        onQuickCommands: openQuickCommands
                    )
                    .padding(.horizontal, 16 * scale)
                    .padding(.bottom, 8 * scale)
                    .onGeometryChange(for: CGFloat.self) { proxy in
                        proxy.size.height
                    } action: { newHeight in
                        chatInputHeight = newHeight
                    }
                }
            }
        }
        .overlay(alignment: .topTrailing) {
            if showHoldingsFilter {
                HoldingsFilterPopup(
                    scale: scale,
                    displayOption: holdingsViewModel.displayOption,
                    sortOption: holdingsViewModel.sortOption,
                    onSelectDisplay: holdingsViewModel.setDisplayOption,
                    onSelectSort: holdingsViewModel.setSortOption,
                    onDismiss: {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                            showHoldingsFilter = false
                        }
                    }
                )
                .padding(.trailing, 36 * scale)
                .padding(.top, 54 * scale)
                .transition(.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity))
            }
        }
        .overlay(alignment: .bottom) {
            if tickerMentionViewModel.isShowingPopup && !anyModalOpen {
                TickerMentionPopup(
                    results: tickerMentionViewModel.results,
                    onSelect: { tickerMentionViewModel.selectResult($0) }
                )
                .padding(.horizontal, 16 * scale)
                .padding(.bottom, chatInputHeight - 8 * scale)
                .transition(.opacity.combined(with: .scale(scale: 0.95, anchor: .bottom)))
            }
        }
        .overlay(alignment: .bottom) { quickCommandsOverlay }
        .animation(.spring(duration: 0.25, bounce: 0.1), value: tickerMentionViewModel.isShowingPopup)
        .background { HomeBackgroundView() }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    baseScale = geo.size.width / 393
                    bottomSafeArea = geo.safeAreaInsets.bottom
                }
            }
        }
        .mask {
            RoundedRectangle(cornerRadius: showSidebar ? 28 * scale : 0)
                .ignoresSafeArea()
        }
        .overlay {
            Button(action: toggleSidebar) {
                Color.clear
                    .contentShape(.rect)
                    .ignoresSafeArea()
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L10n.Home.sidebarDismissAccessibility)
            .accessibilityHidden(!showSidebar)
            .allowsHitTesting(showSidebar)
        }
        .offset(x: showSidebar ? 300 * scale : 0)
        .background {
            SidebarPanelView(
                scale: scale,
                chats: viewModel.chats,
                userName: viewModel.preferredName,
                founderPhoneURL: viewModel.founderPhoneURL(),
                founderTextURL: viewModel.founderTextURL(),
                contactEmailURL: viewModel.contactEmailURL()
            )
        }
        .task { await viewModel.load() }
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
            Button(L10n.Home.fundingLoadErrorDismiss, role: .cancel) {
                fundingViewModel.clearError()
            }
        } message: { message in
            Text(message)
        }
        .modifier(TransferSheetPresenter(
            transferViewModel: transferViewModel,
            fundingViewModel: fundingViewModel,
            scale: scale
        ))
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

    private func dismissTopLayer() {
        if showQuickCommands {
            dismissQuickCommands()
        } else if showHoldingsFilter {
            withAnimation(.spring(duration: 0.3, bounce: 0.15)) { showHoldingsFilter = false }
        } else {
            dismissAllModals()
        }
    }

    private func openQuickCommands() {
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            showQuickCommands = true
        }
    }

    private func dismissQuickCommands() {
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            showQuickCommands = false
        }
    }

    private func selectDiscover() {
        tickerMentionViewModel.updateText("$")
        tickerMentionViewModel.requestFocus()
        dismissQuickCommands()
    }

    private func togglePortfolio() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showPortfolio.toggle()
            showHoldingsFilter = false
        }
    }

    private func toggleFunding() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showFunding.toggle()
            showHoldingsFilter = false
        }
    }

    private func dismissFunding() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showFunding = false
        }
    }

    private func startTransfer(_ direction: TransferDirection) {
        // Collapse the cash detail modal first; the transfer card sheet then appears
        // over the home screen. When chat is built, this state will move to the chat
        // screen's MCP renderer.
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showFunding = false
        }
        transferViewModel.start(direction: direction)
    }

    private func toggleHoldings() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showHoldings.toggle()
            if !showHoldings { showHoldingsFilter = false }
        }
    }

    private func dismissHoldings() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showHoldings = false
            showHoldingsFilter = false
        }
    }

    private func toggleRadar() {
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showRadar.toggle()
            showHoldingsFilter = false
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
            showHoldingsFilter = false
        }
    }

    private func toggleSidebar() {
        withAnimation(.spring(duration: 0.5, bounce: 0.32)) {
            showSidebar.toggle()
        }
    }

    // Re-mounted on each open so QuickCommandsPopup's dragOffset resets cleanly.
    @ViewBuilder
    private var quickCommandsOverlay: some View {
        if showQuickCommands {
            VStack(spacing: 0) {
                Spacer(minLength: 0)
                QuickCommandsPopup(
                    scale: scale,
                    webSearchEnabled: $webSearchEnabled,
                    bottomSafeArea: bottomSafeArea,
                    onDiscover: selectDiscover,
                    onDismiss: dismissQuickCommands
                )
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            .ignoresSafeArea()
        }
    }

    @ViewBuilder
    private var tickerPopupDismissButton: some View {
        Button(action: tickerMentionViewModel.dismiss) {
            Color.clear.contentShape(.rect).ignoresSafeArea()
        }
        .buttonStyle(.plain)
        .accessibilityLabel(L10n.Home.dismissAccessibility)
        .accessibilityHidden(!tickerMentionViewModel.isShowingPopup)
        .allowsHitTesting(tickerMentionViewModel.isShowingPopup)
    }

    private var navSidebarButton: some View {
        Button(action: toggleSidebar) {
            Image(systemName: "sidebar.left")
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.navCircleClear)
        .contentShape(.rect)
        .frame(minWidth: 44 * scale, minHeight: 44 * scale)
        .accessibilityLabel(L10n.Home.sidebarAccessibility)
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
