import SwiftUI

/// A single view that morphs between the small portfolio pill and the expanded modal.
struct PortfolioMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let isHidden: Bool
    let viewModel: PortfolioViewModel
    let onTap: () -> Void

    @Namespace private var morphNamespace

    var body: some View {
        Group {
            if isExpanded {
                expandedCard
            } else if !isHidden {
                pillButton
            }
        }
        .modifier(GlassMorphID(id: "portfolio", namespace: morphNamespace))
    }

    private var pillButton: some View {
        Button(action: onTap) {
            HStack(spacing: 6 * scale) {
                pillContent

                VStack(spacing: -2 * scale) {
                    Image(systemName: "chevron.down")
                    Image(systemName: "chevron.down")
                }
                .font(.system(size: 8 * scale, weight: .bold))
                .foregroundStyle(viewModel.isDown ? Color.sevinoNegative : Color.sevinoPositive)
                .accessibilityHidden(true)
            }
            .padding(.horizontal, 12 * scale)
            .frame(height: 36 * scale)
        }
        .buttonStyle(.bouncePill)
        .modifier(SevinoGlass.navPillClear)
        .contentShape(.rect)
        .frame(minHeight: 44 * scale)
        .accessibilityLabel(L10n.Home.portfolioAccessibility)
        .accessibilityValue(pillAccessibilityValue)
    }

    /// First-load (no successful fetch yet) shows a spinner so the pill
    /// doesn't render a stale `"—"` placeholder. After any fetch completes,
    /// `accountStatus` is non-empty and we route on its kind: non-`ACTIVE`
    /// statuses swap in a short label, `active`/`unknown` render the dollar
    /// value. `unknown` is also the fallback for any future status the
    /// client doesn't recognise — show the value rather than blanking.
    @ViewBuilder
    private var pillContent: some View {
        if viewModel.accountStatus.isEmpty && viewModel.error == nil {
            ProgressView()
                .scaleEffect(0.7)
                .frame(minWidth: 20 * scale)
        } else {
            let kind = AccountStatusKind(rawStatus: viewModel.accountStatus)
            switch kind {
            case .pending, .actionRequired, .rejected:
                AccountStatusPillLabel(kind: kind, scale: scale)
            case .active, .unknown:
                Text(viewModel.displayValue)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
            }
        }
    }

    /// Reads the visible pill text to VoiceOver — without this, users hear
    /// "Portfolio, button" and miss whatever status copy replaced the value.
    /// Mirrors the same first-load condition as `pillContent` so VoiceOver
    /// announces "Loading" instead of the placeholder em-dash while waiting
    /// for the first snapshot.
    private var pillAccessibilityValue: String {
        if viewModel.accountStatus.isEmpty && viewModel.error == nil {
            return L10n.Home.portfolioLoadingAccessibility
        }
        switch AccountStatusKind(rawStatus: viewModel.accountStatus) {
        case .pending: return L10n.Home.accountPendingShort
        case .actionRequired: return L10n.Home.accountActionRequiredShort
        case .rejected: return L10n.Home.accountRejectedShort
        case .active, .unknown: return viewModel.displayValue
        }
    }

    private var expandedCard: some View {
        let statusKind = AccountStatusKind(rawStatus: viewModel.accountStatus)
        let showsValueAndChart = statusKind == .active || statusKind == .unknown
        return ScrollView {
            VStack(alignment: .leading, spacing: 16 * scale) {
                if showsValueAndChart {
                    HStack(spacing: 8 * scale) {
                        Text(viewModel.displayValue)
                            .font(.system(size: 36 * scale, weight: .bold))
                            .foregroundStyle(Color.sevinoSecondary)

                        Text(L10n.Home.portfolioCurrency)
                            .font(.system(size: 18 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoGreyContrast)
                    }

                    PortfolioExpandedContent(scale: scale, viewModel: viewModel)
                } else {
                    AccountStatusMessage(kind: statusKind, scale: scale)
                }
            }
            .padding(16 * scale)
        }
        .refreshable {
            await viewModel.loadPortfolio()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }
}
