import SwiftUI

struct LinkedAccountsSettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    // TODO: Replace with real linked accounts from ViewModel
    @State private var accounts = [
        LinkedAccount(name: "Total Checking", bankName: "Chase Bank", lastFour: "6813", logoDomain: "chase.com"),
        LinkedAccount(name: "Business Checking", bankName: "Mercury", lastFour: "9247", logoDomain: "mercury.com"),
    ]
    @State private var expandedAccountId: UUID?
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        SevinoGlassContainer {
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
                            onToggle: { toggleExpanded(account.id) },
                            onCopy: { copyAccountNumber(account.lastFour) },
                            onUnlink: { unlink(account.id) }
                        )
                    }

                    Spacer()
                }

                Button(action: {}) {
                    Text(L10n.Settings.addAccount)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16 * scale)
                }
                .modifier(SevinoGlass.card)
                .disabled(true)
                .padding(.bottom, 16 * scale)
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    baseScale = geo.size.width / 393
                }
            }
        }
        .navigationBarBackButtonHidden()
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

    private func copyAccountNumber(_ lastFour: String) {
        UIPasteboard.general.string = lastFour
    }

    private func unlink(_ id: UUID) {
        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
            accounts.removeAll { $0.id == id }
        }
    }
}

private struct LinkedAccountRow: View {
    let account: LinkedAccount
    let scale: CGFloat
    let isExpanded: Bool
    let onToggle: () -> Void
    let onCopy: () -> Void
    let onUnlink: () -> Void

    @State private var showUnlinkConfirmation = false

    var body: some View {
        VStack(spacing: 0) {
            Button(action: onToggle) {
                HStack(spacing: 10 * scale) {
                    BankLogoView(domain: account.logoDomain, bankName: account.bankName, size: 28 * scale)

                    Text("\(account.name) • \(account.lastFour)")
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
                    value: account.name,
                    subtitle: account.bankName
                )
                Divider().foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
                detailRow(
                    label: L10n.Settings.accountNumberLabel,
                    value: "****\(account.lastFour)",
                    showCopy: true
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
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                            .padding(.leading, -16 * scale)
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
    let domain: String
    let bankName: String
    let size: CGFloat

    var body: some View {
        AsyncImage(url: URL(string: "https://www.google.com/s2/favicons?domain=\(domain)&sz=128")) { phase in
            switch phase {
            case .success(let image):
                image
                    .resizable()
                    .scaledToFill()
            default:
                Text(String(bankName.prefix(1)))
                    .font(.system(size: size * 0.5, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
            }
        }
        .frame(width: size, height: size)
        .clipShape(.circle)
        .accessibilityLabel(bankName)
    }
}

#Preview("Dark") {
    NavigationStack {
        LinkedAccountsSettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        LinkedAccountsSettingsView()
    }
    .preferredColorScheme(.light)
}
