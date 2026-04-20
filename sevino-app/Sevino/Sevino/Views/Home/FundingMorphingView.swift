import SwiftUI

struct FundingMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    @Bindable var viewModel: HomeViewModel
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
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: isExpanded ? CardGlass.cornerRadius : 50 * scale))
        .gesture(isExpanded ? nil : TapGesture().onEnded { onTap() })
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel(L10n.Home.fundingAccessibility)
    }

    private var pillContent: some View {
        Image(systemName: "dollarsign")
            .font(.system(size: 16 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: 36 * scale, height: 36 * scale)
    }

    private var expandedContent: some View {
        VStack(spacing: 16 * scale) {
            if let message = viewModel.funding.displayedError {
                Text(message)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoNegative)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .transition(.opacity)
            }
            headerSection
            earningsBadge
            statCards
            detailsTable
            actionRow
            infoRow
            disclaimer
        }
        .task(id: isExpanded) {
            if isExpanded {
                await viewModel.funding.loadRelationships()
            }
        }
        .sheet(isPresented: $viewModel.funding.isShowingPlaidLink) {
            if let token = viewModel.funding.linkToken {
                PlaidLinkSheet(
                    linkToken: token,
                    onSuccess: { publicToken, accountId, institutionName, accountMask, accountName in
                        Task {
                            await viewModel.funding.onPlaidSuccess(
                                publicToken: publicToken,
                                accountId: accountId,
                                institutionName: institutionName,
                                accountMask: accountMask,
                                accountName: accountName
                            )
                        }
                    },
                    onExit: { error in
                        viewModel.funding.onPlaidExit(error: error)
                    }
                )
            }
        }
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

    @ViewBuilder
    private var actionRow: some View {
        if viewModel.funding.hasLinkedBank {
            actionButtons
        } else {
            linkBankButton
        }
    }

    private var actionButtons: some View {
        HStack(spacing: 10 * scale) {
            Button(L10n.Home.deposit, action: {})
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.2), in: .rect(cornerRadius: 14 * scale))

            Button(L10n.Home.withdraw, action: {})
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoSecondary, in: .rect(cornerRadius: 14 * scale))
        }
    }

    private var linkBankButton: some View {
        Button {
            Task { await viewModel.funding.startBankLink() }
        } label: {
            Text("Link a bank account")
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoSecondary, in: .rect(cornerRadius: 14 * scale))
        }
        .disabled(viewModel.funding.isLoading)
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

#Preview("Dark") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
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
        Color.sevinoPrimary.ignoresSafeArea()
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
