import SwiftUI

struct HomeView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.textSizeMultiplier) private var textSizeMultiplier
    @State private var viewModel: HomeViewModel
    @State private var portfolioViewModel: PortfolioViewModel
    @State private var fundingViewModel: FundingViewModel
    @State private var holdingsViewModel: HoldingsViewModel
    @State private var radarViewModel: RadarViewModel
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

    init(
        viewModel: HomeViewModel = HomeViewModel(),
        portfolioViewModel: PortfolioViewModel = PortfolioViewModel(),
        fundingViewModel: FundingViewModel = FundingViewModel(),
        holdingsViewModel: HoldingsViewModel = HoldingsViewModel(),
        radarViewModel: RadarViewModel = RadarViewModel()
    ) {
        self._viewModel = State(initialValue: viewModel)
        self._portfolioViewModel = State(initialValue: portfolioViewModel)
        self._fundingViewModel = State(initialValue: fundingViewModel)
        self._holdingsViewModel = State(initialValue: holdingsViewModel)
        self._radarViewModel = State(initialValue: radarViewModel)
    }

    var body: some View {
        SevinoGlassContainer {
            ZStack {
                ZStack {
                    HomeGreetingSection(
                        scale: scale,
                        greeting: viewModel.greeting,
                        showExplore: $showExplore,
                        isHidden: anyModalOpen
                    )
                    .offset(y: -60 * scale)

                    VStack(spacing: 0) {
                        HStack(spacing: 8 * scale) {
                            navSidebarButton
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

                        HomeChatSuggestions(scale: scale, onSelect: { messageText = $0 })
                            .padding(.bottom, 20 * scale)
                            .padding(.horizontal, 16 * scale)

                        HomeChatInputBar(text: $messageText, scale: scale, isDimmed: anyModalOpen)
                            .padding(.horizontal, 16 * scale)
                            .padding(.bottom, 8 * scale)
                    }
                }
                .blur(radius: anyModalOpen ? 10 : 0)
                .brightness(anyModalOpen && colorScheme == .light ? -0.3 : 0)
                .allowsHitTesting(!anyModalOpen)

                Button {
                    if showHoldingsFilter {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) { showHoldingsFilter = false }
                    } else {
                        dismissAllModals()
                    }
                } label: {
                    Color.sevinoPrimary
                        .opacity(anyModalOpen ? 0.4 : 0)
                        .ignoresSafeArea()
                }
                .buttonStyle(.plain)
                .contentShape(Rectangle())
                .accessibilityLabel(L10n.Home.dismissAccessibility)
                .accessibilityHidden(!anyModalOpen)
                .allowsHitTesting(anyModalOpen)

                PortfolioMorphingView(
                    scale: scale,
                    isExpanded: showPortfolio,
                    viewModel: portfolioViewModel,
                    onTap: togglePortfolio
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(.leading, showPortfolio ? 16 * scale : (16 + 44 + 8) * scale)
                .padding(.trailing, showPortfolio ? 16 * scale : 0)
                .padding(.top, 4 * scale)
                .ignoresSafeArea(.keyboard)
                .allowsHitTesting(!showFunding && !showHoldings && !showRadar)
                .accessibilityHidden(showFunding || showHoldings || showRadar)
                .blur(radius: showFunding || showHoldings || showRadar ? 10 : 0)
                .brightness(showFunding || showHoldings || showRadar ? (colorScheme == .light ? -0.3 : -0.2) : 0)

                FundingMorphingView(
                    scale: scale,
                    isExpanded: showFunding,
                    viewModel: fundingViewModel,
                    onTap: toggleFunding,
                    onDismiss: dismissFunding
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(.trailing, showFunding ? 16 * scale : (16 + 44 + 8 + 44 + 8) * scale)
                .padding(.leading, showFunding ? 16 * scale : 0)
                .padding(.top, 4 * scale)
                .ignoresSafeArea(.keyboard)
                .allowsHitTesting(!showPortfolio && !showHoldings && !showRadar)
                .accessibilityHidden(showPortfolio || showHoldings || showRadar)
                .blur(radius: showPortfolio || showHoldings || showRadar ? 10 : 0)
                .brightness(showPortfolio || showHoldings || showRadar ? (colorScheme == .light ? -0.3 : -0.2) : 0)

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
                .accessibilityHidden(showPortfolio || showFunding || showRadar)
                .blur(radius: showPortfolio || showFunding || showRadar ? 10 : 0)
                .brightness(showPortfolio || showFunding || showRadar ? (colorScheme == .light ? -0.3 : -0.2) : 0)

                RadarMorphingView(
                    scale: scale,
                    isExpanded: showRadar,
                    viewModel: radarViewModel,
                    onTap: toggleRadar,
                    onDismiss: dismissRadar
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                .padding(.trailing, showRadar ? 16 * scale : (16 + 44 + 8) * scale)
                .padding(.leading, showRadar ? 16 * scale : 0)
                .padding(.top, 4 * scale)
                .ignoresSafeArea(.keyboard)
                .allowsHitTesting(!showPortfolio && !showFunding && !showHoldings)
                .accessibilityHidden(showPortfolio || showFunding || showHoldings)
                .blur(radius: showPortfolio || showFunding || showHoldings ? 10 : 0)
                .brightness(showPortfolio || showFunding || showHoldings ? (colorScheme == .light ? -0.3 : -0.2) : 0)
            }
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
                .contentShape(.rect)
                .frame(minWidth: 44 * scale, minHeight: 44 * scale)
        }
        .modifier(SevinoGlass.navCircleClear)
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
