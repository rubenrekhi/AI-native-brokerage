import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var authVM = AuthViewModel()
    @State private var settingsVM = SettingsViewModel()
    @State private var showLegalLinks = false
    @State private var showLogOutConfirmation = false
    @State private var path = NavigationPath()
    @State private var baseScale: CGFloat = 1
    #if DEBUG
    @State private var tradeVM = TradeExecutionViewModel()
    @State private var showTradeTest = false
    #endif

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        NavigationStack(path: $path) {
            SevinoGlassContainer {
                VStack(spacing: 0) {
                    header
                        .padding(.bottom, 24 * scale)

                    VStack(spacing: 0) {
                        settingsRow(icon: "person.crop.circle", title: L10n.Settings.accounts, action: navigateToAccounts)
                        settingsRow(icon: "lock", title: L10n.Settings.loginSecurity, action: navigateToLoginSecurity)
                        settingsRow(icon: "doc.text", title: L10n.Settings.personalInfo, action: navigateToPersonalInfo)
                        settingsRow(icon: "paintbrush", title: L10n.Settings.appearance, action: navigateToAppearance)
                        #if DEBUG
                        // Debug-only row — never ships, intentionally hardcoded English.
                        settingsRow(icon: "hammer", title: "Test Trade Execution", action: presentTradeTest)
                        #endif
                    }

                    Spacer()

                    Button(action: confirmLogOut) {
                        Text(L10n.Settings.logOut)
                            .font(.system(size: 16 * scale, weight: .semibold))
                            .foregroundStyle(Color.sevinoSecondary)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16 * scale)
                            .contentShape(.rect(cornerRadius: 14 * scale))
                    }
                    .modifier(SevinoGlass.tintedButton(tint: Color.sevinoNegative, cornerRadius: 14 * scale))
                    .disabled(authVM.isLoading)
                    .confirmationDialog(L10n.Settings.logOutConfirmTitle, isPresented: $showLogOutConfirmation) {
                        Button(L10n.Settings.logOutConfirmAction, role: .destructive, action: logOut)
                    } message: {
                        Text(L10n.Settings.logOutConfirmMessage)
                    }
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
            .task { await settingsVM.load() }
            #if DEBUG
            .sheet(isPresented: $showTradeTest) {
                TradeTestSheet(viewModel: tradeVM)
            }
            #endif
            .navigationDestination(for: SettingsDestination.self) { destination in
                switch destination {
                case .accounts:
                    AccountsSettingsView(settingsVM: settingsVM)
                case .cashEnrollment:
                    CashEnrollmentStatusView()
                case .brokerage:
                    BrokerageSettingsView()
                case .linkedAccounts:
                    LinkedAccountsSettingsView(viewModel: settingsVM)
                case .loginSecurity:
                    LoginSecuritySettingsView(viewModel: settingsVM)
                case .personalInfo:
                    PersonalInfoSettingsView(vm: settingsVM)
                case .appearance:
                    AppearanceSettingsView()
                case .manageFaceId:
                    FaceIDSettingsView()
                case .changePassword:
                    ChangePasswordView(vm: ChangePasswordViewModel())
                case .accountDocuments:
                    DocumentsListView(
                        title: L10n.Settings.accountDocuments,
                        documentType: nil
                    )
                case .statements:
                    DocumentsListView(
                        title: L10n.Settings.statements,
                        documentType: "account_statement"
                    )
                case .taxDocuments:
                    DocumentsListView(
                        title: L10n.Settings.taxDocuments,
                        documentType: "tax_1099"
                    )
                case .accountHistory:
                    AccountHistoryView()
                case .tradeHistory:
                    TradeHistoryView()
                }
            }
        }
    }

    private var header: some View {
        ZStack {
            Text(L10n.Settings.title)
                .font(.system(size: 20 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            HStack {
                Button(L10n.Settings.closeAccessibility, systemImage: "xmark", action: { dismiss() })
                    .labelStyle(.iconOnly)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .modifier(SevinoGlass.navCircleClear)

                Spacer()

                Button(L10n.Settings.legalAccessibility, systemImage: "info.circle", action: { showLegalLinks = true })
                    .labelStyle(.iconOnly)
                    .font(.system(size: 16 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .modifier(SevinoGlass.navCircleClear)
                    .confirmationDialog(L10n.Settings.legalTitle, isPresented: $showLegalLinks) {
                        Button(L10n.Settings.privacyPolicy, action: openPrivacyPolicy)
                        Button(L10n.Settings.termsOfService, action: openTermsOfService)
                        Button(L10n.Settings.acceptableUse, action: openAcceptableUse)
                        Button(L10n.Settings.consumerTerms, action: openConsumerTerms)
                    }
            }
        }
    }

    private func settingsRow(icon: String, title: String, action: (() -> Void)? = nil) -> some View {
        Button(action: action ?? {}) {
            VStack(spacing: 0) {
                HStack {
                    Label(title, systemImage: icon)
                        .labelStyle(SettingsRowLabelStyle(scale: scale))

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.vertical, 16 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
        .disabled(action == nil)
    }

    private func navigateToAccounts() {
        path.append(SettingsDestination.accounts)
    }

    private func navigateToLoginSecurity() {
        path.append(SettingsDestination.loginSecurity)
    }

    private func navigateToPersonalInfo() {
        path.append(SettingsDestination.personalInfo)
    }

    private func navigateToAppearance() {
        path.append(SettingsDestination.appearance)
    }

    #if DEBUG
    private func presentTradeTest() {
        tradeVM.prepareTrade()
        showTradeTest = true
    }

    #endif

    private func confirmLogOut() {
        showLogOutConfirmation = true
    }

    private func logOut() {
        Task { await authVM.signOut() }
    }

    private func openPrivacyPolicy() {
        guard let url = URL(string: "https://sevino.ai/privacy") else { return }
        openURL(url)
    }

    private func openTermsOfService() {
        guard let url = URL(string: "https://sevino.ai/terms") else { return }
        openURL(url)
    }

    private func openAcceptableUse() {
        guard let url = URL(string: "https://sevino.ai/acceptable-use") else { return }
        openURL(url)
    }

    private func openConsumerTerms() {
        guard let url = URL(string: "https://sevino.ai/consumer-terms") else { return }
        openURL(url)
    }
}

private struct SettingsRowLabelStyle: LabelStyle {
    let scale: CGFloat

    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 14 * scale) {
            configuration.icon
                .font(.system(size: 18 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: 28 * scale)

            configuration.title
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
        }
    }
}

#Preview("Dark") {
    SettingsView()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    SettingsView()
        .preferredColorScheme(.light)
}
