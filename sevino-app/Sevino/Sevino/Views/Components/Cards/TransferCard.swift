import SwiftUI

/// MCP chat card that lets the user prepare and confirm an ACH deposit or withdrawal.
///
/// Pure presentation — the card owns only UI-local state (selected bank, amount text,
/// picker expansion). The parent receives the picked `(bankAccountID, amount)` through
/// `onConfirm`. When `onConfirm` is `nil` the confirm button is hidden so the card can
/// render as a read-only MCP preview.
struct TransferCard: View {
    let data: TransferCardData
    var scale: CGFloat = 1
    var onConfirm: ((String, Decimal) -> Void)?
    var onDismiss: (() -> Void)?
    var onLinkBank: (() -> Void)?

    /// Confirmation mode (an AI-proposed transfer). When `prefilledAmount` is set the
    /// amount is fixed and shown read-only, the CTA becomes a hold-to-confirm button
    /// (`onHoldConfirm`), and the settlement disclaimer is dropped. Leaving it `nil`
    /// keeps the interactive entry mode the manual transfer sheet uses.
    var prefilledAmount: Decimal?
    var onHoldConfirm: (() -> Void)?
    var isSubmitting: Bool = false
    var holdTitle: String = ""

    @State private var selectedBankAccountID: String?
    @State private var amountText: String = ""
    @State private var isPickerOpen: Bool = false
    @FocusState private var amountFocused: Bool

    private var isConfirmMode: Bool { prefilledAmount != nil }

    private var selectedBank: TransferBankAccount? {
        guard let id = selectedBankAccountID else { return data.bankAccounts.first }
        return data.bankAccounts.first { $0.id == id } ?? data.bankAccounts.first
    }

    private var amountDecimal: Decimal? {
        guard !amountText.isEmpty else { return nil }
        let normalized = amountText.replacingOccurrences(of: ",", with: ".")
        return Decimal(string: normalized)
    }

    private var exceedsAvailable: Bool {
        guard data.direction == .withdraw,
              let cap = data.availableBalance,
              let amount = amountDecimal else { return false }
        return amount > cap
    }

    private var isAmountValid: Bool {
        guard let amount = amountDecimal, amount > 0 else { return false }
        return !exceedsAvailable
    }

    var body: some View {
        VStack(spacing: 20 * scale) {
            TransferHeader(
                direction: data.direction,
                scale: scale,
                onDismiss: onDismiss
            )

            if data.bankAccounts.isEmpty {
                TransferEmptyBanksView(scale: scale, onLinkBank: onLinkBank)
            } else {
                if let prefilledAmount {
                    TransferStaticAmountDisplay(amount: prefilledAmount, scale: scale)
                } else {
                    TransferAmountDisplay(
                        amountText: $amountText,
                        amountFocused: $amountFocused,
                        direction: data.direction,
                        currencyCode: data.currencyCode,
                        exceedsAvailable: exceedsAvailable,
                        availableBalance: data.availableBalance,
                        scale: scale
                    )
                }

                TransferEndpointStack(
                    direction: data.direction,
                    bankAccounts: data.bankAccounts,
                    selectedBank: selectedBank,
                    brokerageLabel: data.brokerageLabel,
                    isPickerOpen: $isPickerOpen,
                    scale: scale
                )

                if isPickerOpen && data.bankAccounts.count > 1 {
                    TransferAccountsPicker(
                        accounts: data.bankAccounts,
                        selectedID: selectedBankAccountID ?? data.bankAccounts.first?.id,
                        scale: scale,
                        onSelect: selectBank,
                        onLinkAnother: onLinkBank
                    )
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

                if isConfirmMode {
                    TransferHoldCTA(
                        isSubmitting: isSubmitting,
                        holdTitle: holdTitle,
                        onHoldConfirm: onHoldConfirm,
                        scale: scale
                    )
                } else if let onConfirm {
                    TransferConfirmButton(
                        direction: data.direction,
                        amount: amountDecimal,
                        currencyCode: data.currencyCode,
                        exceedsAvailable: exceedsAvailable,
                        isEnabled: isAmountValid,
                        scale: scale,
                        action: { confirm(onConfirm) }
                    )
                }
            }

            if !isConfirmMode {
                Text(L10n.Transfer.disclaimer)
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(20 * scale)
        .background(GenUICardBackground(cornerRadius: 28 * scale))
        .animation(.spring(duration: 0.3, bounce: 0.15), value: isPickerOpen)
        .onAppear {
            if selectedBankAccountID == nil {
                selectedBankAccountID = data.bankAccounts.first?.id
            }
        }
    }

    private func selectBank(_ id: String) {
        selectedBankAccountID = id
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) { isPickerOpen = false }
    }

    private func confirm(_ handler: (String, Decimal) -> Void) {
        guard let bank = selectedBank, let amount = amountDecimal, isAmountValid else { return }
        amountFocused = false
        handler(bank.id, amount)
    }
}

// MARK: - Header (badge + close)

private struct TransferHeader: View {
    let direction: TransferDirection
    let scale: CGFloat
    let onDismiss: (() -> Void)?

    var body: some View {
        HStack(spacing: 0) {
            TransferDirectionBadge(direction: direction, scale: scale)
            Spacer()
            if let onDismiss {
                Button(action: onDismiss) {
                    Image(systemName: "xmark")
                        .font(.system(size: 12 * scale, weight: .bold))
                        .foregroundStyle(TransferPalette.textSecondary)
                        .frame(width: 28 * scale, height: 28 * scale)
                        .background(Circle().fill(TransferPalette.iconBgSubtle))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L10n.Transfer.closeAccessibility)
            }
        }
    }
}

// MARK: - Amount display

private struct TransferAmountDisplay: View {
    @Binding var amountText: String
    var amountFocused: FocusState<Bool>.Binding
    let direction: TransferDirection
    let currencyCode: String
    let exceedsAvailable: Bool
    let availableBalance: Decimal?
    let scale: CGFloat

    private var amountColor: Color {
        exceedsAvailable ? TransferPalette.failRed : TransferPalette.textPrimary
    }

    var body: some View {
        VStack(spacing: 10 * scale) {
            Text(L10n.Transfer.amountLabel.uppercased())
                .font(.system(size: 10 * scale, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(TransferPalette.textMuted)

            HStack(alignment: .firstTextBaseline, spacing: 2 * scale) {
                Text(verbatim: "$")
                    .font(.system(size: 42 * scale, weight: .medium))
                    .foregroundStyle(amountColor.opacity(0.7))
                TextField("", text: $amountText, prompt: Text(verbatim: "0"))
                    .font(.system(size: 64 * scale, weight: .bold))
                    .foregroundStyle(amountColor)
                    .keyboardType(.decimalPad)
                    .focused(amountFocused)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: true, vertical: false)
            }
            .frame(maxWidth: .infinity)
            .contentShape(.rect)
            .onTapGesture { amountFocused.wrappedValue = true }

            if exceedsAvailable, let availableBalance {
                HStack(spacing: 6 * scale) {
                    Image(systemName: "exclamationmark.circle.fill")
                        .font(.system(size: 11 * scale, weight: .semibold))
                    Text(L10n.Transfer.exceedsAvailable(availableBalance.formatted(.currency(code: currencyCode))))
                        .font(.system(size: 12 * scale, weight: .semibold))
                }
                .foregroundStyle(TransferPalette.failRed)
                .padding(.horizontal, 10 * scale)
                .padding(.vertical, 6 * scale)
                .background(
                    Capsule().fill(TransferPalette.failRedMuted)
                )
            }
        }
    }
}

// MARK: - From / To endpoint stack

private struct TransferEndpointStack: View {
    let direction: TransferDirection
    let bankAccounts: [TransferBankAccount]
    let selectedBank: TransferBankAccount?
    let brokerageLabel: String
    @Binding var isPickerOpen: Bool
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 0) {
            rowContent(isSource: true)
            Rectangle()
                .fill(TransferPalette.hairline)
                .frame(height: 1)
                .padding(.leading, 64 * scale)
            rowContent(isSource: false)
        }
        .background(
            RoundedRectangle(cornerRadius: 16 * scale)
                .fill(TransferPalette.chipBackground)
        )
    }

    @ViewBuilder
    private func rowContent(isSource: Bool) -> some View {
        let isBank = (direction == .deposit) == isSource
        if isBank, let bank = selectedBank {
            let canToggle = bankAccounts.count > 1
            Button(action: { togglePicker(canToggle: canToggle) }) {
                TransferEndpointRow(
                    label: isSource ? L10n.Transfer.fromLabel : L10n.Transfer.toLabel,
                    icon: .bank(bank.institutionName),
                    title: bankDisplayName(bank),
                    subtitle: formattedMask(bank),
                    chevron: canToggle ? (isPickerOpen ? "chevron.up" : "chevron.down") : nil,
                    scale: scale
                )
            }
            .buttonStyle(.plain)
            .disabled(!canToggle)
            .accessibilityLabel(L10n.Transfer.selectAccountAccessibility)
        } else {
            TransferEndpointRow(
                label: isSource ? L10n.Transfer.fromLabel : L10n.Transfer.toLabel,
                icon: .brokerage,
                title: L10n.Transfer.brokerageName,
                subtitle: L10n.Transfer.brokerageSubtitle,
                chevron: nil,
                scale: scale
            )
        }
    }

    private func togglePicker(canToggle: Bool) {
        guard canToggle else { return }
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) { isPickerOpen.toggle() }
    }

    private func bankDisplayName(_ bank: TransferBankAccount) -> String {
        if let nickname = bank.nickname, !nickname.isEmpty { return nickname }
        return bank.institutionName
    }

    private func formattedMask(_ bank: TransferBankAccount) -> String {
        if let nickname = bank.nickname, !nickname.isEmpty {
            return L10n.Transfer.bankAccountFormat(bank.institutionName, bank.accountMask)
        }
        return "•••• \(bank.accountMask)"
    }
}

private struct TransferEndpointRow: View {
    let label: String
    let icon: AccountAvatar.Kind
    let title: String
    let subtitle: String
    let chevron: String?
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 14 * scale) {
            AccountAvatar(kind: icon, scale: scale)

            VStack(alignment: .leading, spacing: 3 * scale) {
                Text(label.uppercased())
                    .font(.system(size: 10 * scale, weight: .semibold))
                    .tracking(1)
                    .foregroundStyle(TransferPalette.textMuted)
                Text(title)
                    .font(.system(size: 17 * scale, weight: .semibold))
                    .foregroundStyle(TransferPalette.textPrimary)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(TransferPalette.textTertiary)
                    .lineLimit(1)
            }

            Spacer(minLength: 0)

            if let chevron {
                Image(systemName: chevron)
                    .font(.system(size: 12 * scale, weight: .semibold))
                    .foregroundStyle(TransferPalette.textMuted)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 16 * scale)
        .padding(.vertical, 14 * scale)
        .contentShape(.rect)
    }
}

// MARK: - Accounts picker

private struct TransferAccountsPicker: View {
    let accounts: [TransferBankAccount]
    let selectedID: String?
    let scale: CGFloat
    let onSelect: (String) -> Void
    let onLinkAnother: (() -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            Text(L10n.Transfer.linkedAccountsHeader)
                .font(.system(size: 10 * scale, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(TransferPalette.textMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16 * scale)
                .padding(.top, 14 * scale)
                .padding(.bottom, 6 * scale)

            ForEach(accounts) { account in
                TransferAccountPickerRow(
                    account: account,
                    isSelected: account.id == selectedID,
                    isLast: account.id == accounts.last?.id,
                    scale: scale,
                    onSelect: onSelect
                )
            }

            if let onLinkAnother {
                Rectangle().fill(TransferPalette.dividerSubtle)
                    .frame(height: 1)
                    .padding(.leading, 66 * scale)
                Button(action: onLinkAnother) {
                    HStack(spacing: 14 * scale) {
                        Image(systemName: "plus")
                            .font(.system(size: 16 * scale, weight: .bold))
                            .foregroundStyle(TransferPalette.textPrimary.opacity(0.7))
                            .frame(width: 36 * scale, height: 36 * scale)
                            .background(Circle().fill(TransferPalette.iconBgHairline))
                        Text(L10n.Transfer.linkAnotherCta)
                            .font(.system(size: 15 * scale, weight: .semibold))
                            .foregroundStyle(TransferPalette.textPrimary.opacity(0.75))
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 16 * scale)
                    .padding(.vertical, 12 * scale)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 16 * scale)
                .fill(TransferPalette.chipBackground)
        )
    }
}

private struct TransferAccountPickerRow: View {
    let account: TransferBankAccount
    let isSelected: Bool
    let isLast: Bool
    let scale: CGFloat
    let onSelect: (String) -> Void

    private var displayName: String {
        if let nickname = account.nickname, !nickname.isEmpty { return nickname }
        return account.institutionName
    }

    var body: some View {
        VStack(spacing: 0) {
            Button(action: { onSelect(account.id) }) {
                HStack(spacing: 14 * scale) {
                    AccountAvatar(kind: .bank(account.institutionName), scale: scale)
                    VStack(alignment: .leading, spacing: 2 * scale) {
                        Text(displayName)
                            .font(.system(size: 15 * scale, weight: .semibold))
                            .foregroundStyle(TransferPalette.textPrimary)
                        Text(L10n.Transfer.bankTypeMaskFormat(account.accountType.capitalized, account.accountMask))
                            .font(.system(size: 12 * scale))
                            .foregroundStyle(TransferPalette.textTertiary)
                    }
                    Spacer(minLength: 0)
                    if isSelected {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 18 * scale, weight: .semibold))
                            .foregroundStyle(TransferPalette.depositGreen)
                    }
                }
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 10 * scale)
                .contentShape(.rect)
            }
            .buttonStyle(.plain)

            if !isLast {
                Rectangle().fill(TransferPalette.dividerSubtle)
                    .frame(height: 1)
                    .padding(.leading, 66 * scale)
            }
        }
    }
}

// MARK: - Confirm button

private struct TransferConfirmButton: View {
    let direction: TransferDirection
    let amount: Decimal?
    let currencyCode: String
    let exceedsAvailable: Bool
    let isEnabled: Bool
    let scale: CGFloat
    let action: () -> Void

    private var title: String {
        if exceedsAvailable { return L10n.Transfer.amountExceedsCta }
        guard let amount, amount > 0 else { return L10n.Transfer.amountEmptyCta }
        let formatted = amount.formatted(.currency(code: currencyCode))
        return direction == .deposit
            ? L10n.Transfer.confirmDepositAmount(formatted)
            : L10n.Transfer.confirmWithdrawAmount(formatted)
    }

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 16 * scale, weight: .bold))
                .foregroundStyle(isEnabled ? TransferPalette.confirmEnabledText : TransferPalette.confirmDisabledText)
                .frame(maxWidth: .infinity, minHeight: 52 * scale)
                .background(
                    Capsule().fill(isEnabled ? TransferPalette.confirmEnabled : TransferPalette.confirmDisabledBg)
                )
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .animation(.easeInOut(duration: 0.15), value: isEnabled)
    }
}

// MARK: - Confirmation mode (read-only amount + hold-to-confirm)

private struct TransferStaticAmountDisplay: View {
    let amount: Decimal
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 10 * scale) {
            Text(L10n.Transfer.amountLabel.uppercased())
                .font(.system(size: 10 * scale, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(TransferPalette.textMuted)

            HStack(alignment: .firstTextBaseline, spacing: 2 * scale) {
                Text(verbatim: "$")
                    .font(.system(size: 42 * scale, weight: .medium))
                    .foregroundStyle(TransferPalette.textPrimary.opacity(0.7))
                Text(amount.formatted(.number.precision(.fractionLength(0...2))))
                    .font(.system(size: 64 * scale, weight: .bold))
                    .foregroundStyle(TransferPalette.textPrimary)
            }
            .frame(maxWidth: .infinity)
        }
    }
}

private struct TransferHoldCTA: View {
    let isSubmitting: Bool
    let holdTitle: String
    let onHoldConfirm: (() -> Void)?
    let scale: CGFloat

    var body: some View {
        if isSubmitting {
            HStack(spacing: 8 * scale) {
                ProgressView().controlSize(.small)
                Text(L10n.Confirmation.submitting)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(TransferPalette.textSecondary)
            }
            .frame(maxWidth: .infinity, minHeight: 38 * scale)
        } else if let onHoldConfirm {
            HoldToConfirmButton(
                title: holdTitle,
                scale: scale,
                action: onHoldConfirm
            )
        }
    }
}

// MARK: - Empty state

private struct TransferEmptyBanksView: View {
    let scale: CGFloat
    let onLinkBank: (() -> Void)?

    var body: some View {
        VStack(spacing: 10 * scale) {
            Text(L10n.Transfer.noBanksTitle)
                .font(.system(size: 18 * scale, weight: .semibold))
                .foregroundStyle(TransferPalette.textPrimary)
                .multilineTextAlignment(.center)
            Text(L10n.Transfer.noBanksMessage)
                .font(.system(size: 13 * scale))
                .foregroundStyle(TransferPalette.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            if let onLinkBank {
                Button(action: onLinkBank) {
                    Text(L10n.Transfer.linkBankCta)
                        .font(.system(size: 16 * scale, weight: .bold))
                        .foregroundStyle(TransferPalette.confirmEnabledText)
                        .frame(maxWidth: .infinity, minHeight: 48 * scale)
                        .background(Capsule().fill(TransferPalette.confirmEnabled))
                }
                .buttonStyle(.plain)
                .padding(.top, 6 * scale)
            }
        }
        .padding(20 * scale)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 16 * scale)
                .fill(TransferPalette.chipBackground)
        )
    }
}

// MARK: - Previews

private let previewBankChase = TransferBankAccount(
    id: "bank-1",
    institutionName: "Chase",
    accountMask: "4821",
    accountType: "CHECKING",
    nickname: nil
)

private let previewBankMulti: [TransferBankAccount] = [
    previewBankChase,
    TransferBankAccount(
        id: "bank-2",
        institutionName: "Schwab Bank",
        accountMask: "9102",
        accountType: "SAVINGS",
        nickname: nil
    ),
    TransferBankAccount(
        id: "bank-3",
        institutionName: "Ally",
        accountMask: "7733",
        accountType: "SAVINGS",
        nickname: nil
    ),
    TransferBankAccount(
        id: "bank-4",
        institutionName: "Wells Fargo",
        accountMask: "0255",
        accountType: "CHECKING",
        nickname: nil
    ),
]

#Preview("Deposit · amount entered") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferCard(
            data: TransferCardData(
                direction: .deposit,
                bankAccounts: [previewBankChase],
                brokerageLabel: L10n.Transfer.brokerageName,
                availableBalance: nil,
                currencyCode: "USD"
            ),
            onConfirm: { id, amount in print("deposit \(amount) from \(id)") },
            onDismiss: { print("dismiss") }
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Confirmation · hold to confirm") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferCard(
            data: TransferCardData(
                direction: .deposit,
                bankAccounts: [previewBankChase],
                brokerageLabel: L10n.Transfer.brokerageName,
                availableBalance: nil,
                currencyCode: "USD"
            ),
            prefilledAmount: 500,
            onHoldConfirm: {},
            holdTitle: "Hold to deposit"
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Withdrawal · exceeds balance") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferCard(
            data: TransferCardData(
                direction: .withdraw,
                bankAccounts: [previewBankChase],
                brokerageLabel: L10n.Transfer.brokerageName,
                availableBalance: 2412.08,
                currencyCode: "USD"
            ),
            onConfirm: { _, _ in },
            onDismiss: {}
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Multi-account · picker") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferCard(
            data: TransferCardData(
                direction: .deposit,
                bankAccounts: previewBankMulti,
                brokerageLabel: L10n.Transfer.brokerageName,
                availableBalance: nil,
                currencyCode: "USD"
            ),
            onConfirm: { _, _ in },
            onDismiss: {},
            onLinkBank: { print("link another") }
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Empty banks") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferCard(
            data: TransferCardData(
                direction: .deposit,
                bankAccounts: [],
                brokerageLabel: L10n.Transfer.brokerageName,
                availableBalance: nil,
                currencyCode: "USD"
            ),
            onLinkBank: { print("link bank") }
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Read-only (MCP)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferCard(
            data: TransferCardData(
                direction: .deposit,
                bankAccounts: [previewBankChase],
                brokerageLabel: L10n.Transfer.brokerageName,
                availableBalance: nil,
                currencyCode: "USD"
            )
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}
