import SwiftUI

struct CashDetailCard: View {
    let data: CashCardData
    var scale: CGFloat = 1
    var onDeposit: (() -> Void)?
    var onWithdraw: (() -> Void)?
    var onLinkBank: (() -> Void)?
    var onReconnectBank: (() -> Void)?
    var onInfoTap: (() -> Void)?
    var isPrimaryActionDisabled: Bool = false

    private var balanceText: String {
        data.balance.formatted(.currency(code: "USD"))
    }

    private var apyText: String {
        data.apy.formatted(.percent.precision(.fractionLength(2)))
    }

    private var thisMonthEarnedText: String {
        signedCurrency(data.thisMonthEarned)
    }

    private var lifetimeEarnedText: String {
        signedCurrency(data.lifetimeEarned)
    }

    private var lifetimeSinceText: String? {
        data.lifetimeSince?.formatted(.dateTime.month(.abbreviated).year())
    }

    private var buyingPowerText: String {
        data.buyingPower.formatted(.currency(code: "USD"))
    }

    private var pendingDepositsText: String {
        data.pendingDeposits.formatted(.currency(code: "USD"))
    }

    private var fdicInsuredText: String {
        data.fdicInsuredLimit.formatted(.currency(code: "USD").precision(.fractionLength(0)))
    }

    private var interestPaidOutText: String {
        data.interestPaidOut.rawValue.capitalized
    }

    private var daysAccruedText: String {
        data.daysAccrued.formatted()
    }

    var body: some View {
        VStack(spacing: 16 * scale) {
            headerSection
            earningsBadge
            statCards
            detailsTable
            if showsActionRow {
                actionRow
            }
            infoRow
            disclaimer
        }
    }

    private var showsActionRow: Bool {
        if data.reauthRelationshipId != nil {
            return onReconnectBank != nil
        }
        if data.hasLinkedBank {
            return onDeposit != nil || onWithdraw != nil
        }
        return onLinkBank != nil
    }

    private var headerSection: some View {
        VStack(spacing: 4 * scale) {
            Text(L10n.Home.uninvestedCash)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(balanceText)
                .font(.system(size: 36 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
                .accessibilityLabel(balanceText)
        }
    }

    private var earningsBadge: some View {
        Text(L10n.Home.earningApy(apyText))
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
                value: thisMonthEarnedText,
                subtitle: L10n.Home.daysAccrued(daysAccruedText)
            )
            statCard(
                title: L10n.Home.lifetimeEarned,
                value: lifetimeEarnedText,
                subtitle: lifetimeSinceText.map(L10n.Home.sinceLabel)
            )
        }
    }

    private func statCard(title: String, value: String, subtitle: String?) -> some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(title)
                .font(.system(size: 12 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
            Text(value)
                .font(.system(size: 22 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoPositive)
            if let subtitle {
                Text(subtitle)
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
    }

    private var detailsTable: some View {
        VStack(spacing: 0) {
            detailRow(label: L10n.Home.currentApy, value: apyText)
            detailRow(label: L10n.Home.buyingPower, value: buyingPowerText)
            detailRow(label: L10n.Home.pendingDeposits, value: pendingDepositsText)
            detailRow(label: L10n.Home.interestPaidOut, value: interestPaidOutText)
            detailRow(label: L10n.Home.fdicInsured, value: fdicInsuredText, isLast: true)
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
        if data.reauthRelationshipId != nil, let onReconnectBank {
            primaryActionButton(
                title: L10n.Home.reconnectBankAction,
                action: onReconnectBank
            )
        } else if data.hasLinkedBank {
            depositWithdrawButtons
        } else if let onLinkBank {
            primaryActionButton(
                title: L10n.Home.linkBankAccount,
                action: onLinkBank
            )
        }
    }

    @ViewBuilder
    private var depositWithdrawButtons: some View {
        HStack(spacing: 10 * scale) {
            if let onDeposit {
                Button(L10n.Home.deposit, action: onDeposit)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoPrimary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14 * scale)
                    .background(Color.sevinoSecondary, in: .rect(cornerRadius: 14 * scale))
            }

            if let onWithdraw {
                Button(L10n.Home.withdraw, action: onWithdraw)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14 * scale)
                    .background(Color.sevinoGreyAccent.opacity(0.2), in: .rect(cornerRadius: 14 * scale))
            }
        }
    }

    private func primaryActionButton(
        title: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 15 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPrimary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoSecondary, in: .rect(cornerRadius: 14 * scale))
        }
        .disabled(isPrimaryActionDisabled)
    }

    @ViewBuilder
    private var infoRow: some View {
        if let onInfoTap {
            Button(action: onInfoTap) {
                infoRowContent(showsChevron: true)
            }
        } else {
            infoRowContent(showsChevron: false)
        }
    }

    private func infoRowContent(showsChevron: Bool) -> some View {
        HStack {
            Image(systemName: "info.circle")
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
                .accessibilityHidden(true)

            Text(L10n.Home.cashInterestInfo)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)

            Spacer()

            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .accessibilityHidden(true)
            }
        }
        .padding(12 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.15), in: .rect(cornerRadius: 12 * scale))
    }

    private var disclaimer: some View {
        Text(L10n.Home.cashDisclaimer)
            .font(.system(size: 10 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func signedCurrency(_ amount: Decimal) -> String {
        let formatted = amount.formatted(.currency(code: "USD"))
        return amount >= 0 ? "+\(formatted)" : formatted
    }
}

private extension CashCardData {
    static let previewLinked = CashCardData(
        balance: 2412.08,
        apy: 0.032,
        thisMonthEarned: 6.43,
        daysAccrued: 22,
        lifetimeEarned: 41.87,
        lifetimeSince: DateComponents(calendar: .current, year: 2025, month: 10, day: 1).date ?? Date(),
        buyingPower: 2412.08,
        pendingDeposits: 100.50,
        interestPaidOut: .monthly,
        fdicInsuredLimit: 2_500_000,
        hasLinkedBank: true,
        reauthRelationshipId: nil
    )

    static let previewUnlinked = CashCardData(
        balance: 0,
        apy: 0.032,
        thisMonthEarned: 0,
        daysAccrued: 0,
        lifetimeEarned: 0,
        lifetimeSince: DateComponents(calendar: .current, year: 2025, month: 10, day: 1).date ?? Date(),
        buyingPower: 0,
        pendingDeposits: 0,
        interestPaidOut: .monthly,
        fdicInsuredLimit: 2_500_000,
        hasLinkedBank: false,
        reauthRelationshipId: nil
    )

    static let previewNeedsReauth = CashCardData(
        balance: 2412.08,
        apy: 0.032,
        thisMonthEarned: 6.43,
        daysAccrued: 22,
        lifetimeEarned: 41.87,
        lifetimeSince: DateComponents(calendar: .current, year: 2025, month: 10, day: 1).date ?? Date(),
        buyingPower: 2412.08,
        pendingDeposits: 100.50,
        interestPaidOut: .monthly,
        fdicInsuredLimit: 2_500_000,
        hasLinkedBank: true,
        reauthRelationshipId: UUID()
    )
}

#Preview("Linked bank") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CashDetailCard(
            data: .previewLinked,
            onDeposit: { print("deposit tapped") },
            onWithdraw: { print("withdraw tapped") },
            onInfoTap: { print("info tapped") }
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Unlinked bank") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CashDetailCard(
            data: .previewUnlinked,
            onLinkBank: { print("link bank tapped") }
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Read-only (MCP)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CashDetailCard(data: .previewLinked)
            .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Bank needs reauth") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CashDetailCard(
            data: .previewNeedsReauth,
            onDeposit: { print("deposit tapped") },
            onWithdraw: { print("withdraw tapped") },
            onReconnectBank: { print("reconnect tapped") }
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Bank needs reauth (light)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        CashDetailCard(
            data: .previewNeedsReauth,
            onDeposit: { print("deposit tapped") },
            onWithdraw: { print("withdraw tapped") },
            onReconnectBank: { print("reconnect tapped") }
        )
        .padding(20)
    }
    .preferredColorScheme(.light)
}
