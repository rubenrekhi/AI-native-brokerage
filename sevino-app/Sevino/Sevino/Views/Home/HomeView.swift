import Combine
import SwiftUI

struct HomeView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.textSizeMultiplier) private var textSizeMultiplier
    @Environment(\.scenePhase) private var scenePhase
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
    @State private var sidebarDragOffset: CGFloat = 0
    @State private var showQuickCommands = false
    @State private var webSearchEnabled = false
    @State private var bottomSafeArea: CGFloat = 0

    private var sidebarWidth: CGFloat { 300 * scale }
    private var sidebarOffset: CGFloat { (showSidebar ? sidebarWidth : 0) + sidebarDragOffset }

    // Captured as `let` so SwiftUI re-evaluations don't subscribe to a fresh
    // publisher each pass.
    private let portfolioRefreshTimer = Timer.publish(every: 300, on: .main, in: .common).autoconnect()

    private var anyModalOpen: Bool { showPortfolio || showFunding || showHoldings || showRadar }
    private var anyDismissableLayerOpen: Bool { anyModalOpen || showHoldingsFilter || showQuickCommands }

    private func modalDimBrightness(when isDimmed: Bool) -> Double {
        guard isDimmed else { return 0 }
        return colorScheme == .light ? -0.3 : -0.2
    }

    private var radarErrorAlertPresented: Binding<Bool> {
        Binding(
            get: { radarViewModel.error != nil },
            set: { if !$0 { radarViewModel.clearError() } }
        )
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
                if !viewModel.isConversationActive {
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
                    .transition(.opacity.combined(with: .offset(y: 20)))
                }

                chatContentLayer

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
                .refreshOnPresent(showPortfolio) { await portfolioViewModel.loadPortfolio() }

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
                .refreshOnPresent(showHoldings) { await holdingsViewModel.loadHoldings() }

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

                inputBarLayer
            }
        }
        .animation(.spring(duration: 0.4, bounce: 0.1), value: viewModel.isConversationActive)
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
        .overlay(alignment: .topTrailing) { holdingsFilterOverlay }
        .background { HomeBackgroundView() }
        .onGeometryChange(for: CGSize.self) { geo in
            geo.size
        } action: { size in
            baseScale = size.width / 393
        }
        .onGeometryChange(for: EdgeInsets.self) { geo in
            geo.safeAreaInsets
        } action: { insets in
            bottomSafeArea = insets.bottom
        }
        .overlay(alignment: .leading) {
            Color.clear
                .frame(width: 44 * scale)
                .contentShape(.rect)
                .gesture(sidebarDragGesture)
                .padding(.top, 60 * scale)
                .allowsHitTesting(!showSidebar)
                .accessibilityHidden(true)
        }
        .mask {
            RoundedRectangle(cornerRadius: showSidebar ? 28 * scale : 0)
                .ignoresSafeArea()
        }
        .overlay { sidebarDismissOverlay }
        .offset(x: sidebarOffset)
        .background {
            SidebarPanelView(
                scale: scale,
                chats: viewModel.chats,
                userName: viewModel.preferredName,
                founderPhoneURL: viewModel.founderPhoneURL(),
                founderTextURL: viewModel.founderTextURL(),
                contactEmailURL: viewModel.contactEmailURL(),
                activeConversationId: viewModel.isConversationActive
                    ? viewModel.conversationStore.conversationId
                    : nil,
                onSelectChat: { conversationId in
                    Task { await resumeConversation(conversationId) }
                },
                onNewChat: {
                    viewModel.startNewConversation()
                    withAnimation(.spring(duration: 0.5, bounce: 0.32)) {
                        showSidebar = false
                        sidebarDragOffset = 0
                    }
                },
                onDeleteChat: { conversationId in
                    Task { await viewModel.deleteConversation(conversationId) }
                }
            )
        }
        .task { await viewModel.load() }
        .onChange(of: viewModel.turnState) { oldState, newState in
            if oldState == .streaming && newState == .idle {
                Task { await viewModel.refreshChats() }
            }
        }
        .task { await holdingsViewModel.loadHoldings() }
        .task { await radarViewModel.loadRadar() }
        .task(id: portfolioViewModel.selectedTimeRange) {
            await portfolioViewModel.loadPortfolio()
        }
        .modifier(PortfolioAutoRefresh(
            scenePhase: scenePhase,
            timer: portfolioRefreshTimer,
            refresh: { await portfolioViewModel.loadSnapshot() }
        ))
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
        .modifier(ResumeErrorAlert(viewModel: viewModel))
        .modifier(TransferSheetPresenter(
            transferViewModel: transferViewModel,
            fundingViewModel: fundingViewModel,
            scale: scale
        ))
        .alert(
            L10n.Home.radarLoadErrorTitle,
            isPresented: radarErrorAlertPresented,
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

    // TODO(SEV-567): replace this string collapse with structured ticker
    // mentions in the wire payload so the backend doesn't have to re-parse.
    private func retryLastMessage() {
        guard let lastUserMessage = viewModel.messages.last(where: { $0.role == .user }),
              let textBlock = lastUserMessage.blocks.first,
              case .text(let tb) = textBlock else { return }
        Task {
            do {
                try await viewModel.send(text: tb.text)
            } catch {
                // Failure reflected in conversation store's turn state.
            }
        }
    }

    private func sendMessage(segments: [MessageSegment]) {
        let text = segments.map { segment -> String in
            switch segment {
            case .text(let value): return value
            case .ticker(let symbol): return "$\(symbol)"
            }
        }.joined()
        guard !text.isEmpty else { return }

        let attached = captureAttachedContext()
        if anyModalOpen {
            dismissAllModals()
        }

        tickerMentionViewModel.clear()
        Task {
            do {
                try await viewModel.send(text: text, context: attached?.wireContext, attachedContext: attached)
            } catch {
                // Failure is already reflected in the conversation store's
                // turn state; user-facing surfacing of send errors is post-v0.
            }
        }
    }

    private func captureAttachedContext() -> AttachedContext? {
        if showPortfolio {
            return .portfolio(
                equity: portfolioViewModel.equity,
                currency: portfolioViewModel.currency,
                gainAbs: portfolioViewModel.gainAbs,
                gainPct: portfolioViewModel.gainPct,
                timeRange: portfolioViewModel.selectedTimeRange.rawValue
            )
        }
        if showFunding {
            return .funding(
                balance: fundingViewModel.cashBalance,
                apy: fundingViewModel.cashApy,
                buyingPower: fundingViewModel.cashBuyingPower
            )
        }
        if showHoldings {
            return .holdings(holdings: holdingsViewModel.holdings.map {
                HoldingSummary(
                    ticker: $0.ticker,
                    marketValue: $0.marketValue,
                    unrealizedPl: $0.unrealizedPl
                )
            })
        }
        if showRadar {
            return .radar(items: radarViewModel.radarItems.map {
                RadarSummary(
                    ticker: $0.ticker,
                    description: $0.description,
                    price: $0.price,
                    changePercent: $0.changePercent,
                    isPositive: $0.isPositive
                )
            })
        }
        return nil
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
        let text: String = switch direction {
        case .deposit: L10n.Home.chatPrefillDeposit
        case .withdraw: L10n.Home.chatPrefillWithdraw
        }
        withAnimation(.spring(duration: 0.5, bounce: 0.15)) {
            showFunding = false
        }
        tickerMentionViewModel.prefill(text)
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
            sidebarDragOffset = 0
        }
    }

    /// Tap-to-resume handler for sidebar rows. Closes the sidebar
    /// optimistically (the chat surface overlay reads `messages` from the
    /// new store) and then calls `HomeViewModel.resume(conversationId:)`,
    /// which loads the persisted transcript and parks any failure on
    /// `viewModel.resumeError` for the alert below to surface.
    private func resumeConversation(_ conversationId: UUID) async {
        withAnimation(.spring(duration: 0.5, bounce: 0.32)) {
            showSidebar = false
            sidebarDragOffset = 0
        }
        await viewModel.resume(conversationId: conversationId)
    }

    private var sidebarDragGesture: some Gesture {
        DragGesture(minimumDistance: 10)
            .onChanged(handleSidebarDragChanged)
            .onEnded(handleSidebarDragEnded)
    }

    private func handleSidebarDragChanged(_ value: DragGesture.Value) {
        let translation = value.translation.width
        sidebarDragOffset = showSidebar
            ? max(-sidebarWidth, min(0, translation))
            : max(0, min(sidebarWidth, translation))
    }

    private func handleSidebarDragEnded(_ value: DragGesture.Value) {
        let predicted = value.predictedEndTranslation.width
        let threshold = sidebarWidth * 0.3
        withAnimation(.spring(duration: 0.5, bounce: 0.32)) {
            if showSidebar, predicted < -threshold {
                showSidebar = false
            } else if !showSidebar, predicted > threshold {
                showSidebar = true
            }
            sidebarDragOffset = 0
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
                .padding(.horizontal, 3)
                .padding(.bottom, 3)
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

    private var inputBarLayer: some View {
        VStack {
            Spacer()
            HomeChatInputBar(
                viewModel: tickerMentionViewModel,
                scale: scale,
                isDimmed: anyModalOpen,
                isStreaming: viewModel.turnState == .streaming,
                onSend: sendMessage,
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

    @ViewBuilder
    private var chatContentLayer: some View {
        if viewModel.isConversationActive {
            MessageListView(
                messages: viewModel.messages,
                turnState: viewModel.turnState,
                scale: scale,
                onRetry: retryLastMessage
            )
            .safeAreaPadding(.top, 56 * scale)
            .safeAreaPadding(.bottom, chatInputHeight + 48 * scale)
            .blur(radius: anyModalOpen ? 10 : 0)
            .brightness(modalDimBrightness(when: anyModalOpen))
            .allowsHitTesting(!anyModalOpen)
            .accessibilityHidden(anyModalOpen)
            .transition(.opacity)
        } else {
            VStack(spacing: 0) {
                Spacer()

                ShortcutsRail(scale: scale, onSelect: { tickerMentionViewModel.updateText($0) })
                    .padding(.bottom, chatInputHeight + 20 * scale)
                    .padding(.horizontal, 16 * scale)
                    .blur(radius: anyModalOpen ? 10 : 0)
                    .brightness(modalDimBrightness(when: anyModalOpen))
                    .allowsHitTesting(!anyModalOpen)
            }
            .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
    }

    @ViewBuilder
    private var holdingsFilterOverlay: some View {
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

    private var sidebarDismissOverlay: some View {
        Button(action: toggleSidebar) {
            Color.clear
                .contentShape(.rect)
                .ignoresSafeArea()
        }
        .buttonStyle(.plain)
        .highPriorityGesture(sidebarDragGesture)
        .accessibilityLabel(L10n.Home.sidebarDismissAccessibility)
        .accessibilityHidden(!showSidebar)
        .allowsHitTesting(showSidebar)
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

/// Refreshes the portfolio pill every 5 minutes while the scene is `.active`
/// and on every transition back to `.active`. Combine timers keep firing while
/// the app is backgrounded, so the timer branch also gates on `scenePhase`.
/// Extracted from `HomeView.body` to keep the type-checker under budget.
private struct PortfolioAutoRefresh: ViewModifier {
    let scenePhase: ScenePhase
    let timer: Publishers.Autoconnect<Timer.TimerPublisher>
    let refresh: @Sendable () async -> Void

    func body(content: Content) -> some View {
        content
            .onReceive(timer) { _ in
                guard scenePhase == .active else { return }
                Task { await refresh() }
            }
            .onChange(of: scenePhase) { _, newPhase in
                if newPhase == .active {
                    Task { await refresh() }
                }
            }
    }
}

/// Extracts the resume-failure alert from `HomeView` so the parent body
/// type-checks within the compiler's budget — the surrounding view already
/// stacks half a dozen modal alerts and was breaching the threshold.
private struct ResumeErrorAlert: ViewModifier {
    @Bindable var viewModel: HomeViewModel

    func body(content: Content) -> some View {
        content.alert(
            L10n.Sidebar.resumeErrorTitle,
            isPresented: Binding(
                get: { viewModel.resumeError != nil },
                set: { if !$0 { viewModel.clearResumeError() } }
            ),
            presenting: viewModel.resumeError
        ) { _ in
            Button(L10n.Sidebar.resumeErrorDismiss, role: .cancel) {
                viewModel.clearResumeError()
            }
        } message: { message in
            Text(message)
        }
    }
}

#Preview("Dark") {
    HomeView(
        viewModel: HomeViewModel(
            chatService: PlaceholderRecentChatsService.shared
        ),
        radarViewModel: RadarViewModel(client: PlaceholderRadarAPIClient())
    )
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    HomeView(
        viewModel: HomeViewModel(
            chatService: PlaceholderRecentChatsService.shared
        ),
        radarViewModel: RadarViewModel(client: PlaceholderRadarAPIClient())
    )
    .preferredColorScheme(.light)
}
