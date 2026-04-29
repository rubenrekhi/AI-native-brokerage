import SwiftUI

struct FundingMorphingView: View {
    let scale: CGFloat
    let isExpanded: Bool
    let isHidden: Bool
    @Bindable var viewModel: FundingViewModel
    let onTap: () -> Void
    let onDismiss: () -> Void
    var onDeposit: (() -> Void)?
    var onWithdraw: (() -> Void)?

    @Namespace private var morphNamespace

    private var cashCardData: CashCardData {
        CashCardData(
            balance: viewModel.cashBalance,
            apy: viewModel.cashApy,
            thisMonthEarned: viewModel.cashThisMonthEarned,
            daysAccrued: viewModel.cashDaysAccrued,
            lifetimeEarned: viewModel.cashLifetimeEarned,
            lifetimeSince: viewModel.cashLifetimeSince,
            buyingPower: viewModel.cashBuyingPower,
            pendingDeposits: viewModel.cashPendingDeposits,
            interestPaidOut: viewModel.cashInterestPaidOut,
            fdicInsuredLimit: viewModel.cashFdicInsuredLimit,
            hasLinkedBank: viewModel.hasLinkedBank
        )
    }

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
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 36 * scale, height: 36 * scale)
        }
        .buttonStyle(.bouncePill)
        .modifier(SevinoGlass.navCircleClear)
        .contentShape(.rect)
        .frame(minWidth: 44 * scale, minHeight: 44 * scale)
        .accessibilityLabel(L10n.Home.fundingAccessibility)
    }

    private var expandedCard: some View {
        @Bindable var plaidLink = viewModel.plaidLink

        return CashDetailCard(
            data: cashCardData,
            scale: scale,
            onDeposit: onDeposit,
            onWithdraw: onWithdraw,
            onLinkBank: plaidLink.requestBankLink,
            isLinkBankDisabled: viewModel.isLoading || plaidLink.isLoading
        )
        .padding(20 * scale)
        .frame(maxWidth: .infinity)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
        .transition(.asymmetric(
            insertion: .opacity.animation(.easeIn(duration: 0.25).delay(0.15)),
            removal: .identity
        ))
        .task(id: isExpanded) {
            if isExpanded {
                await viewModel.loadRelationships()
            }
        }
        .sheet(isPresented: $plaidLink.showPlaidLink) {
            if let token = plaidLink.linkToken {
                PlaidLinkSheet(
                    linkToken: token,
                    onSuccess: { publicToken, accountId, institutionName, accountMask, accountName in
                        Task {
                            await plaidLink.onPlaidSuccess(
                                publicToken: publicToken,
                                accountId: accountId,
                                institutionName: institutionName,
                                accountMask: accountMask,
                                accountName: accountName
                            )
                        }
                    },
                    onExit: { error in
                        plaidLink.onPlaidExit(error: error)
                    }
                )
            }
        }
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
