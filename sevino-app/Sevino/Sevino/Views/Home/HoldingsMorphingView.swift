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

    private var expandedCard: some View {
        expandedContent
            .padding(20 * scale)
            .frame(maxWidth: .infinity, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .modifier(SevinoGlass.card)
            .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }

    private var expandedContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16 * scale) {
                headerRow
                expandedBody
            }
        }
        .refreshable {
            await viewModel.reload()
        }
        .transition(.asymmetric(
            insertion: .opacity.animation(.easeIn(duration: 0.25).delay(0.15)),
            removal: .identity
        ))
    }

    /// Routes to one of: loading, error, account-status message, fully-empty
    /// state, or the row list. When holdings contains only the CASH row we
    /// render the list (so the user sees their cash balance) plus a small
    /// hint nudging them to add a stock — replacing it with an empty state
    /// would hide the cash they actually have.
    @ViewBuilder
    private var expandedBody: some View {
        let statusKind = AccountStatusKind(rawStatus: viewModel.accountStatus)
        if viewModel.isLoading, viewModel.holdings.isEmpty {
            loadingState
        } else if viewModel.error != nil, viewModel.holdings.isEmpty {
            errorState
        } else if statusKind == .pending || statusKind == .actionRequired || statusKind == .rejected {
            AccountStatusMessage(kind: statusKind, scale: scale)
        } else if viewModel.holdings.isEmpty {
            unfundedEmptyState
        } else {
            LazyVStack(spacing: 12 * scale) {
                ForEach(viewModel.holdings) { holding in
                    HoldingRow(holding: holding, scale: scale)
                }
                if onlyCashRow {
                    cashOnlyHint
                }
            }
        }
    }

    private var onlyCashRow: Bool {
        viewModel.holdings.count == 1 && viewModel.holdings[0].isCash
    }

    private var loadingState: some View {
        ProgressView()
            .frame(maxWidth: .infinity)
            .padding(.vertical, 32 * scale)
    }

    /// Inline nudge for funded ACTIVE accounts that haven't bought anything
    /// yet. Sits below the CASH row instead of replacing it so users still
    /// see their cash balance.
    private var cashOnlyHint: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "magnifyingglass.circle")
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
            Text(L10n.Home.holdingsCashOnlyHint)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.top, 8 * scale)
    }

    /// `ACTIVE` account with no positions and no cash row — the user still
    /// needs to fund. Funded-but-empty no longer routes here; it falls
    /// through to the row list with `cashOnlyHint`.
    private var unfundedEmptyState: some View {
        ContentUnavailableView {
            Label(L10n.Home.holdingsEmptyUnfundedTitle, systemImage: "dollarsign.circle")
        } description: {
            Text(L10n.Home.holdingsEmptyUnfundedMessage)
        }
        .frame(maxWidth: .infinity)
    }

    private var errorState: some View {
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
                .frame(minHeight: 44 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 22 * scale))
        }
        .frame(maxWidth: .infinity)
    }

    private func retry() {
        Task { await viewModel.loadHoldings() }
    }

    private var headerRow: some View {
        HStack {
            Text(L10n.Home.holdingsTitle)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            Spacer()

            Button {
                withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                    showFilter.toggle()
                }
            } label: {
                HStack(spacing: 6 * scale) {
                    Text(viewModel.displayOption.label)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)

                    Image(systemName: "line.3.horizontal.decrease")
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
            }
        }
        .zIndex(1)
    }
}

private struct HoldingRow: View {
    let holding: Holding
    let scale: CGFloat
    @State private var isDetailExpanded = false

    private var hasDetails: Bool { holding.averageCostText != nil }

    var body: some View {
        VStack(spacing: 0) {
            mainRow
            if isDetailExpanded, hasDetails {
                detailSection
            }
        }
        .clipped()
    }

    private var mainRow: some View {
        Button {
            withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                isDetailExpanded.toggle()
            }
        } label: {
            HStack(spacing: 10 * scale) {
                holdingIcon
                tickerInfo
                Spacer()
                valueInfo

                if hasDetails {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .rotationEffect(.degrees(isDetailExpanded ? -180 : 0))
                        .accessibilityHidden(true)
                }
            }
            .padding(.vertical, 8 * scale)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(!hasDetails)
    }

    private var holdingIcon: some View {
        Group {
            if holding.isCash {
                Image(systemName: "dollarsign.circle.fill")
                    .font(.system(size: 28 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 36 * scale, height: 36 * scale)
            } else {
                StockLogoView(ticker: holding.ticker, size: 28 * scale)
            }
        }
    }

    private var tickerInfo: some View {
        VStack(alignment: .leading, spacing: 2 * scale) {
            Text(holding.ticker)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            if let shares = holding.sharesText {
                Text(L10n.Home.holdingsShares(shares))
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }

    private var valueInfo: some View {
        VStack(alignment: .trailing, spacing: 2 * scale) {
            Text(holding.valueText)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)

            if let gainLoss = holding.gainLossText, let isPositive = holding.isPositive {
                Text(gainLoss)
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(isPositive ? Color.sevinoPositive : Color.sevinoNegative)
            }
        }
    }

    private var detailSection: some View {
        VStack(spacing: 0) {
            Text(L10n.Home.holdingsMyHoldings)
                .font(.system(size: 15 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, 8 * scale)

            if let totalGain = holding.gainLossText {
                detailRow(
                    label: L10n.Home.holdingsTotalGain,
                    value: totalGain,
                    isPositive: holding.isPositive
                )
            }

            if let avgCost = holding.averageCostText {
                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(L10n.Home.holdingsAverageCost)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Text(avgCost)
                        .font(.system(size: 18 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 8 * scale)
            }
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
        .padding(.top, 8 * scale)
        .transition(.opacity)
    }

    private func detailRow(label: String, value: String, isPositive: Bool?) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
            Spacer()
            Text(value)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(isPositive == true ? Color.sevinoPositive : Color.sevinoNegative)
        }
        .padding(.vertical, 6 * scale)
    }
}

private struct HoldingsMorphingPreview: View {
    @State private var viewModel = HoldingsViewModel(service: PlaceholderHoldingsService.shared)

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
        .task { await viewModel.loadHoldings() }
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
