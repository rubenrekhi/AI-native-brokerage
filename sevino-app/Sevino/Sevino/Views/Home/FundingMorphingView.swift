import SwiftUI

struct FundingMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let viewModel: HomeViewModel
    let onTap: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: isExpanded ? .center : .leading, spacing: isExpanded ? 0 : 0) {
            if isExpanded {
                expandedContent
            } else {
                pillContent
            }
        }
        .padding(isExpanded ? 20 * scale : 0)
        .frame(maxWidth: isExpanded ? .infinity : nil, alignment: isExpanded ? .center : .leading)
        .fixedSize(horizontal: !isExpanded, vertical: true)
        .modifier(SaturnGlass.card)
        .clipShape(.rect(cornerRadius: isExpanded ? CardGlass.cornerRadius : 50 * scale))
        .gesture(isExpanded ? nil : TapGesture().onEnded { onTap() })
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(L10n.Home.fundingAccessibility)
    }

    private var pillContent: some View {
        Image(systemName: "dollarsign")
            .font(.system(size: 16 * scale, weight: .medium))
            .foregroundStyle(Color.saturnSecondary)
            .frame(width: 36 * scale, height: 36 * scale)
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
    }

    private var headerSection: some View {
        VStack(spacing: 4 * scale) {
            Text(L10n.Home.uninvestedCash)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.saturnGreyContrast)

            Text(viewModel.cashBalance)
                .font(.system(size: 36 * scale, weight: .bold))
                .foregroundStyle(Color.saturnSecondary)
        }
    }

    private var earningsBadge: some View {
        Text(L10n.Home.earningApy(viewModel.cashApy))
            .font(.system(size: 13 * scale, weight: .semibold))
            .foregroundStyle(Color.saturnPositive)
            .padding(.horizontal, 14 * scale)
            .padding(.vertical, 6 * scale)
            .background(Color.saturnPositive.opacity(0.15), in: .capsule)
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
                .foregroundStyle(Color.saturnSecondary)
            Text(value)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.saturnPositive)
            Text(subtitle)
                .font(.system(size: 11 * scale))
                .foregroundStyle(Color.saturnGreyContrast)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12 * scale)
        .background(Color.saturnGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
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
        .background(Color.saturnGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
    }

    private func detailRow(label: String, value: String, isLast: Bool = false) -> some View {
        VStack(spacing: 0) {
            HStack {
                Text(label)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.saturnSecondary)
                Spacer()
                Text(value)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.saturnSecondary)
            }
            .padding(.vertical, 8 * scale)

            if !isLast {
                Divider()
                    .foregroundStyle(Color.saturnGreyAccent.opacity(0.3))
            }
        }
    }

    private var actionButtons: some View {
        HStack(spacing: 10 * scale) {
            Button(L10n.Home.deposit, action: {})
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.saturnSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.saturnGreyAccent.opacity(0.2), in: .rect(cornerRadius: 14 * scale))

            Button(L10n.Home.withdraw, action: {})
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.saturnPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.saturnSecondary, in: .rect(cornerRadius: 14 * scale))
        }
    }

    private var infoRow: some View {
        Button(action: {}) {
            HStack {
                Image(systemName: "info.circle")
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.saturnGreyContrast)
                    .accessibilityHidden(true)

                Text(L10n.Home.cashInterestInfo)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.saturnSecondary)

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(Color.saturnGreyContrast)
                    .accessibilityHidden(true)
            }
            .padding(12 * scale)
            .background(Color.saturnGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
        }
    }

    private var disclaimer: some View {
        Text(L10n.Home.cashDisclaimer)
            .font(.system(size: 10 * scale))
            .foregroundStyle(Color.saturnGreyContrast)
            .fixedSize(horizontal: false, vertical: true)
    }
}

#Preview("Dark") {
    ZStack {
        Color.saturnPrimary.ignoresSafeArea()
        FundingMorphingView(
            scale: 1,
            isExpanded: true,
            viewModel: {
                let vm = HomeViewModel()
                vm.loadGreeting()
                return vm
            }(),
            onTap: {},
            onDismiss: {}
        )
        .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    ZStack {
        Color.saturnPrimary.ignoresSafeArea()
        FundingMorphingView(
            scale: 1,
            isExpanded: true,
            viewModel: {
                let vm = HomeViewModel()
                vm.loadGreeting()
                return vm
            }(),
            onTap: {},
            onDismiss: {}
        )
        .padding(16)
    }
    .preferredColorScheme(.light)
}
