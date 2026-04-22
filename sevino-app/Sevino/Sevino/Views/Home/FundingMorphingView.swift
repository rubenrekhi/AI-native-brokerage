import SwiftUI

struct FundingMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let isHidden: Bool
    let viewModel: FundingViewModel
    let onTap: () -> Void
    let onDismiss: () -> Void

    @Namespace private var morphNamespace

    var body: some View {
        Group {
            if isExpanded {
                expandedCard
            } else if !isHidden {
                pillButton
            }
        }
        .modifier(GlassMorphID(id: "funding", namespace: morphNamespace))
    }

    private var pillButton: some View {
        Button(action: onTap) {
            Image(systemName: "dollarsign")
                .font(.system(size: 16 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 44 * scale, height: 44 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.navCircleClear)
        .accessibilityLabel(L10n.Home.fundingAccessibility)
    }

    private var expandedCard: some View {
        expandedContent
            .padding(20 * scale)
            .frame(maxWidth: .infinity)
            .fixedSize(horizontal: false, vertical: true)
            .modifier(SevinoGlass.card)
            .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }

    private var expandedContent: some View {
        VStack(spacing: 16 * scale) {
            headerSection
            earningsBadge
            statCards
            detailsTable
            actionButtons
            infoRow
            disclaimer
        }
        .transition(.asymmetric(
            insertion: .opacity.animation(.easeIn(duration: 0.25).delay(0.15)),
            removal: .identity
        ))
    }

    private var headerSection: some View {
        VStack(spacing: 4 * scale) {
            Text(L10n.Home.uninvestedCash)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(viewModel.cashBalance)
                .font(.system(size: 36 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
        }
    }

    private var earningsBadge: some View {
        Text(L10n.Home.earningApy(viewModel.cashApy))
            .font(.system(size: 13 * scale, weight: .semibold))
            .foregroundStyle(Color.sevinoPositive)
            .padding(.horizontal, 14 * scale)
            .padding(.vertical, 6 * scale)
            .background(Color.sevinoPositive.opacity(0.15), in: .capsule)
    }

    private var statCards: some View {
        HStack(spacing: 10 * scale) {
            statCard(
                title: L10n.Home.thisMonth,
                value: viewModel.cashThisMonth,
                subtitle: L10n.Home.daysAccrued(viewModel.cashDaysAccrued)
            )
            statCard(
                title: L10n.Home.lifetimeEarned,
                value: viewModel.cashLifetime,
                subtitle: L10n.Home.sinceLabel(viewModel.cashLifetimeSince)
            )
        }
    }

    private func statCard(title: String, value: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(title)
                .font(.system(size: 12 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
            Text(value)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoPositive)
            Text(subtitle)
                .font(.system(size: 11 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
    }

    private var detailsTable: some View {
        VStack(spacing: 0) {
            detailRow(label: L10n.Home.currentApy, value: viewModel.cashApy)
            detailRow(label: L10n.Home.buyingPower, value: viewModel.cashBuyingPower)
            detailRow(label: L10n.Home.pendingDeposits, value: viewModel.cashPendingDeposits)
            detailRow(label: L10n.Home.interestPaidOut, value: viewModel.cashInterestPaidOut)
            detailRow(label: L10n.Home.fdicInsured, value: viewModel.cashFdicInsured, isLast: true)
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
    }

    private func detailRow(label: String, value: String, isLast: Bool = false) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(label)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
                Spacer()
                Text(value)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
            }
            .padding(.vertical, 8 * scale)

            if !isLast {
                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
    }

    private var actionButtons: some View {
        HStack(spacing: 10 * scale) {
            Button(L10n.Home.deposit, action: {})
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoSecondary, in: .rect(cornerRadius: 14 * scale))

            Button(L10n.Home.withdraw, action: {})
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.2), in: .rect(cornerRadius: 14 * scale))
        }
    }

    private var infoRow: some View {
        Button(action: {}) {
            HStack {
                Image(systemName: "info.circle")
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .accessibilityHidden(true)

                Text(L10n.Home.cashInterestInfo)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .accessibilityHidden(true)
            }
            .padding(12 * scale)
            .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
        }
    }

    private var disclaimer: some View {
        Text(L10n.Home.cashDisclaimer)
            .font(.system(size: 10 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct FundingMorphingPreview: View {
    @State private var viewModel = FundingViewModel()

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()
            FundingMorphingView(
                scale: 1,
                isExpanded: true,
                isHidden: false,
                viewModel: viewModel,
                onTap: {},
                onDismiss: {}
            )
            .padding(16)
        }
        .task { await viewModel.loadFundingData() }
    }
}

#Preview("Dark") {
    FundingMorphingPreview()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    FundingMorphingPreview()
        .preferredColorScheme(.light)
}
