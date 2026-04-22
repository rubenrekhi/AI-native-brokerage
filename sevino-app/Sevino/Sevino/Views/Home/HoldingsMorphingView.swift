import SwiftUI

struct HoldingsMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let viewModel: HoldingsViewModel
    @Binding var showFilter: Bool
    let onTap: () -> Void
    let onDismiss: () -> Void

    @Namespace private var morphNamespace

    var body: some View {
        ZStack(alignment: .topTrailing) {
            card

            if showFilter {
                HoldingsFilterPopup(
                    scale: scale,
                    displayOption: viewModel.displayOption,
                    sortOption: viewModel.sortOption,
                    onSelectDisplay: viewModel.setDisplayOption,
                    onSelectSort: viewModel.setSortOption,
                    onDismiss: { withAnimation(.spring(duration: 0.3, bounce: 0.15)) { showFilter = false } }
                )
                .offset(x: -20 * scale, y: 50 * scale)
                .transition(.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity))
                .zIndex(10)
            }
        }
    }

    private var card: some View {
        VStack(alignment: isExpanded ? .leading : .center, spacing: 0) {
            if isExpanded {
                expandedContent
            } else {
                pillContent
            }
        }
        .padding(isExpanded ? 20 * scale : 0)
        .frame(maxWidth: isExpanded ? .infinity : nil, alignment: isExpanded ? .leading : .center)
        .fixedSize(horizontal: !isExpanded, vertical: true)
        .modifier(SevinoGlass.card)
        .modifier(GlassMorphID(id: "holdings", namespace: morphNamespace))
        .clipShape(.rect(cornerRadius: isExpanded ? CardGlass.cornerRadius : 50 * scale))
        .frame(minWidth: isExpanded ? nil : 44 * scale, minHeight: isExpanded ? nil : 44 * scale)
        .contentShape(Rectangle())
        .overlay {
            if !isExpanded {
                Button(action: onTap) { Color.clear.contentShape(.rect) }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.Home.menuAccessibility)
            }
        }
    }

    private var pillContent: some View {
        Image(systemName: "list.bullet")
            .font(.system(size: 16 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: 36 * scale, height: 36 * scale)
    }

    private var expandedContent: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            headerRow

            if viewModel.isLoading, viewModel.holdings.isEmpty {
                loadingState
            } else if viewModel.error != nil, viewModel.holdings.isEmpty {
                errorState
            } else if viewModel.holdings.isEmpty {
                emptyState
            } else {
                LazyVStack(spacing: 12 * scale) {
                    ForEach(viewModel.holdings) { holding in
                        HoldingRow(holding: holding, scale: scale)
                    }
                }
            }
        }
        .transition(.opacity.animation(.easeIn(duration: 0.25).delay(0.15)))
    }

    private var loadingState: some View {
        ProgressView()
            .frame(maxWidth: .infinity)
            .padding(.vertical, 32 * scale)
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(L10n.Home.holdingsEmptyTitle, systemImage: "chart.pie")
        } description: {
            Text(L10n.Home.holdingsEmptyMessage)
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
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 20 * scale))
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

private struct HoldingsFilterPopup: View {
    let scale: CGFloat
    let displayOption: HoldingsDisplayOption
    let sortOption: HoldingsSortOption
    let onSelectDisplay: (HoldingsDisplayOption) -> Void
    let onSelectSort: (HoldingsSortOption) -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.Home.filterDisplayBy)
                .font(.system(size: 11 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .padding(.bottom, 6 * scale)

            ForEach(HoldingsDisplayOption.allCases) { option in
                filterRow(label: option.label, isSelected: option == displayOption) {
                    onSelectDisplay(option)
                    onDismiss()
                }
            }

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
                .padding(.vertical, 8 * scale)

            Text(L10n.Home.filterSortBy)
                .font(.system(size: 11 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .padding(.bottom, 6 * scale)

            ForEach(HoldingsSortOption.allCases) { option in
                filterRow(label: option.label, isSelected: option == sortOption) {
                    onSelectSort(option)
                    onDismiss()
                }
            }
        }
        .padding(12 * scale)
        .frame(width: 180 * scale)
        .background(Color.sevinoSettingsContrast, in: .rect(cornerRadius: 16 * scale))
        .shadow(color: Color.sevinoPrimary.opacity(0.3), radius: 12, y: 4)
    }

    private func filterRow(label: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                Text(label)
                    .font(.system(size: 13 * scale, weight: isSelected ? .semibold : .regular))
                    .foregroundStyle(isSelected ? Color.sevinoSecondary : Color.sevinoGreyContrast)
                Spacer()
                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
            }
            .padding(.vertical, 6 * scale)
            .contentShape(.rect)
        }
    }
}

private struct HoldingRow: View {
    let holding: Holding
    let scale: CGFloat
    @State private var isDetailExpanded = false

    private var hasDetails: Bool { holding.daysGain != nil }

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

            if let shares = holding.shares {
                Text(L10n.Home.holdingsShares(shares))
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }

    private var valueInfo: some View {
        VStack(alignment: .trailing, spacing: 2 * scale) {
            Text(holding.value)
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
        VStack(alignment: .leading, spacing: 12 * scale) {
            VStack(spacing: 0) {
                Text(L10n.Home.holdingsMyHoldings)
                    .font(.system(size: 15 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.bottom, 8 * scale)

                if let daysGain = holding.daysGain, let daysPercent = holding.daysGainPercent {
                    detailRow(
                        label: L10n.Home.holdingsDaysGain,
                        value: "\(daysGain) (\(daysPercent))",
                        isPositive: holding.isPositive
                    )
                }

                if let totalGain = holding.totalGain, let totalPercent = holding.totalGainPercent {
                    detailRow(
                        label: L10n.Home.holdingsTotalGain,
                        value: "\(totalGain) (\(totalPercent))",
                        isPositive: holding.isPositive
                    )
                }

                if let avgCost = holding.averageCost {
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

            Button(L10n.Home.chatAboutThis, action: {})
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 12 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 24 * scale))
        }
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
    @State private var viewModel = HoldingsViewModel()

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()
            HoldingsMorphingView(
                scale: 1,
                isExpanded: true,
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
