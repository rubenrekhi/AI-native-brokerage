import SwiftUI

struct LinkedAccountsSettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @Bindable var viewModel: SettingsViewModel

    @State private var expandedAccountId: UUID?
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    private var accounts: [AchRelationshipDTO] {
        viewModel.profile?.linkedAccounts ?? []
    }

    var body: some View {
        @Bindable var plaidLink = viewModel.plaidLink

        return SevinoGlassContainer {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                if accounts.isEmpty {
                    emptyState
                } else {
                    ForEach(accounts) { account in
                        LinkedAccountRow(
                            account: account,
                            scale: scale,
                            isExpanded: expandedAccountId == account.id,
                            isBusy: viewModel.isLoading,
                            onToggle: { toggleExpanded(account.id) },
                            onCopy: { copyAccountNumber(account.accountMask ?? "") },
                            onUnlink: { unlink(account.id) }
                        )
                    }

                    Spacer()
                }

                Button(action: plaidLink.requestBankLink) {
                    Text(L10n.Settings.addAccount)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16 * scale)
                }
                .modifier(SevinoGlass.card)
                .disabled(viewModel.isLoading || plaidLink.isLoading)
                .padding(.bottom, 16 * scale)
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .navigationBarBackButtonHidden()
        .alert(
            L10n.Settings.unlinkErrorTitle,
            isPresented: Binding(
                get: { viewModel.error != nil },
                set: { if !$0 { viewModel.clearError() } }
            ),
            presenting: viewModel.error
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: viewModel.clearError)
        } message: { message in
            Text(message)
        }
        .alert(
            L10n.Settings.linkErrorTitle,
            isPresented: $plaidLink.showError,
            presenting: plaidLink.displayedError
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: plaidLink.clearErrors)
        } message: { message in
            Text(message)
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

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.linkedAccounts, scale: scale, onBack: { dismiss() })
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label(L10n.Settings.linkedAccountsEmptyTitle, systemImage: "link")
        } description: {
            Text(L10n.Settings.linkedAccountsEmptyMessage)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func toggleExpanded(_ id: UUID) {
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            expandedAccountId = expandedAccountId == id ? nil : id
        }
    }

    private func copyAccountNumber(_ mask: String) {
        guard !mask.isEmpty else { return }
        UIPasteboard.general.string = mask
    }

    private func unlink(_ id: UUID) {
        Task { await viewModel.unlinkAccount(id) }
    }
}

private struct LinkedAccountRow: View {
    let account: AchRelationshipDTO
    let scale: CGFloat
    let isExpanded: Bool
    let isBusy: Bool
    let onToggle: () -> Void
    let onCopy: () -> Void
    let onUnlink: () -> Void

    @State private var showUnlinkConfirmation = false

    private var displayName: String {
        account.nickname ?? account.accountType ?? account.institutionName ?? ""
    }

    private var bankName: String {
        account.institutionName ?? ""
    }

    private var mask: String {
        account.accountMask ?? ""
    }

    private var hasMask: Bool { !mask.isEmpty }

    private var accountNumberValue: String {
        hasMask ? "••••\(mask)" : L10n.Settings.unknownValue
    }

    private var titleText: String {
        hasMask ? "\(displayName) • \(mask)" : displayName
    }

    var body: some View {
        VStack(spacing: 0) {
            Button(action: onToggle) {
                HStack(spacing: 10 * scale) {
                    BankLogoView(bankName: bankName, size: 28 * scale)

                    Text(titleText)
                        .font(.system(size: 16 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    Image(systemName: isExpanded ? "chevron.up" : "chevron.right")
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.vertical, 14 * scale)
            }

            if isExpanded {
                expandedContent
            }

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
        }
    }

    private var expandedContent: some View {
        VStack(spacing: 12 * scale) {
            VStack(spacing: 0) {
                detailRow(
                    label: L10n.Settings.accountName,
                    value: displayName,
                    subtitle: bankName
                )
                Divider().foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
                detailRow(
                    label: L10n.Settings.accountNumberLabel,
                    value: accountNumberValue,
                    showCopy: hasMask
                )
            }
            .padding(14 * scale)
            .modifier(SevinoGlass.card)

            Button(action: { showUnlinkConfirmation = true }) {
                Text(L10n.Settings.unlinkAccount)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12 * scale)
                    .contentShape(.rect(cornerRadius: 14 * scale))
            }
            .modifier(SevinoGlass.tintedButton(tint: Color.sevinoNegative, cornerRadius: 14 * scale))
            .disabled(isBusy)
            .confirmationDialog(L10n.Settings.unlinkConfirmTitle, isPresented: $showUnlinkConfirmation) {
                Button(L10n.Settings.unlinkConfirmAction, role: .destructive, action: onUnlink)
            } message: {
                Text(L10n.Settings.unlinkConfirmMessage)
            }
            .padding(.bottom, 8 * scale)
        }
        .transition(.opacity.animation(.easeIn(duration: 0.2)))
    }

    private func detailRow(label: String, value: String, subtitle: String? = nil, showCopy: Bool = false) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoSecondary)

            Spacer()

            VStack(alignment: .trailing, spacing: 2 * scale) {
                HStack(spacing: 0) {
                    Text(value)
                        .font(.system(size: 14 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)

                    if showCopy {
                        Button(L10n.Settings.copyAccessibility, systemImage: "doc.on.doc", action: onCopy)
                            .labelStyle(.iconOnly)
                            .font(.system(size: 12 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoGreyContrast)
                            .frame(minWidth: 44, minHeight: 44, alignment: .trailing)
                            .contentShape(Rectangle())
                            .padding(.leading, -24 * scale)
                            .padding(.vertical, -8 * scale)
                    }
                }

                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
        }
        .padding(.vertical, 8 * scale)
    }
}

private struct BankLogoView: View {
    let bankName: String
    let size: CGFloat

    private var initial: String {
        bankName.first.map(String.init) ?? "•"
    }

    private var accessibilityLabel: String {
        bankName.isEmpty ? L10n.Settings.unknownBankAccessibility : bankName
    }

    var body: some View {
        Text(initial)
            .font(.system(size: size * 0.5, weight: .bold))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: size, height: size)
            .background(Color.sevinoGreyAccent.opacity(0.2), in: .circle)
            .accessibilityLabel(accessibilityLabel)
    }
}

#Preview("Dark") {
    NavigationStack {
        LinkedAccountsSettingsView(viewModel: SettingsViewModel())
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        LinkedAccountsSettingsView(viewModel: SettingsViewModel())
    }
    .preferredColorScheme(.light)
}
