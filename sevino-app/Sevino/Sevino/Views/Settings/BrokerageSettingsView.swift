import SwiftUI

struct BrokerageSettingsView: View {
    private static let usdCurrency: Decimal.FormatStyle.Currency = .currency(code: "USD")

    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: SettingsViewModel
    @State private var accountName = L10n.Settings.brokerageAccountNameDefault
    @State private var renameItem: RenameItem?
    @State private var showCloseConfirmation = false
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    private var accountNumber: String {
        vm.profile?.brokerage?.accountNumber ?? L10n.Settings.unavailableValue
    }

    private var accountValueText: String {
        guard let equity = vm.accountValue?.equity else { return L10n.Settings.unavailableValue }
        return equity.formatted(Self.usdCurrency)
    }

    private var netDepositsText: String {
        guard let cash = vm.accountValue?.cash else { return L10n.Settings.unavailableValue }
        return cash.formatted(Self.usdCurrency)
    }

    private var isInitialLoad: Bool {
        vm.isLoading && vm.profile == nil && vm.accountValue == nil
    }

    init(vm: SettingsViewModel = SettingsViewModel()) {
        _vm = State(initialValue: vm)
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                accountSection
                    .padding(.bottom, 24 * scale)

                VStack(spacing: 0) {
                    navRow(title: L10n.Settings.accountDocuments, destination: .accountDocuments)
                    navRow(title: L10n.Settings.statements, destination: .statements)
                    navRow(title: L10n.Settings.taxDocuments, destination: .taxDocuments)
                    navRow(title: L10n.Settings.accountHistory, destination: .accountHistory)
                    navRow(title: L10n.Settings.tradeHistory, destination: .tradeHistory)
                }

                Spacer()

                Button(action: { showCloseConfirmation = true }) {
                    closeAccountLabel
                }
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoNegative, cornerRadius: 14 * scale))
                .disabled(vm.isClosingBrokerage || vm.didCloseBrokerage)
                .confirmationDialog(
                    L10n.Settings.closeAccountConfirmTitle,
                    isPresented: $showCloseConfirmation,
                    titleVisibility: .visible
                ) {
                    Button(L10n.Settings.closeAccountConfirmAction, role: .destructive, action: closeBrokerageAccount)
                } message: {
                    Text(L10n.Settings.closeAccountConfirmMessage)
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
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    baseScale = geo.size.width / 393
                }
            }
        }
        .navigationBarBackButtonHidden()
        .task { await vm.load() }
        .overlay(alignment: .top) {
            if vm.didCloseBrokerage {
                CloseAccountSuccessBanner(scale: scale)
                    .padding(.top, 8 * scale)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.25), value: vm.didCloseBrokerage)
        .task(id: vm.didCloseBrokerage) {
            guard vm.didCloseBrokerage else { return }
            try? await Task.sleep(for: .milliseconds(1200))
            guard !Task.isCancelled else { return }
            dismiss()
            vm.resetCloseBrokerageFlag()
        }
        .modifier(CloseBrokerageAlertModifier(vm: vm))
    }

    @ViewBuilder
    private var closeAccountLabel: some View {
        if vm.isClosingBrokerage {
            ProgressView()
                .tint(Color.sevinoSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16 * scale)
                .contentShape(.rect(cornerRadius: 14 * scale))
        } else {
            Text(L10n.Settings.closeAccount)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16 * scale)
                .contentShape(.rect(cornerRadius: 14 * scale))
        }
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.brokerage, scale: scale, onBack: { dismiss() })
    }

    private var accountSection: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            HStack {
                Text(accountName)
                    .font(.system(size: 22 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)

                Spacer()

                Button(L10n.Settings.renameAccessibility, systemImage: "pencil.line", action: presentRename)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
            .popupCard(item: $renameItem) { item in
                AccountRenameSheet(item: item, scale: scale) { newName in
                    accountName = newName
                }
            }

            VStack(spacing: 0) {
                if isInitialLoad {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 24 * scale)
                } else if let error = vm.error, vm.profile == nil && vm.accountValue == nil {
                    errorState(message: error)
                } else {
                    accountDetailRow(label: L10n.Settings.accountNumber, value: accountNumber, showCopy: true)
                    accountDetailRow(label: L10n.Settings.accountValue, value: accountValueText)
                    accountDetailRow(label: L10n.Settings.netDeposits, value: netDepositsText, isLast: true)
                }
            }
            .padding(14 * scale)
            .modifier(SevinoGlass.card)
        }
    }

    private func accountDetailRow(label: String, value: String, showCopy: Bool = false, isLast: Bool = false) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                Text(label)
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.sevinoSecondary)

                Spacer()

                Text(value)
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)

                if showCopy {
                    Button(L10n.Settings.copyAccessibility, systemImage: "doc.on.doc", action: copyAccountNumber)
                        .labelStyle(.iconOnly)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .frame(minWidth: 44, minHeight: 44, alignment: .trailing)
                        .contentShape(Rectangle())
                        .padding(.leading, -24 * scale)
                        .padding(.vertical, -8 * scale)
                }
            }
            .padding(.vertical, 8 * scale)

            if !isLast {
                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
    }

    private func errorState(message: String) -> some View {
        VStack(spacing: 12 * scale) {
            Text(message)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoNegative)
                .multilineTextAlignment(.center)

            Button(action: { Task { await vm.reload() } }) {
                Text(L10n.General.tryAgain)
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(minHeight: 44)
                    .padding(.horizontal, 16 * scale)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16 * scale)
    }

    private func navRow(title: String, destination: SettingsDestination) -> some View {
        NavigationLink(value: destination) {
            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.vertical, 16 * scale)
                .frame(minHeight: 44)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
    }

    private func copyAccountNumber() {
        guard let number = vm.profile?.brokerage?.accountNumber else { return }
        UIPasteboard.general.string = number
    }

    private func presentRename() {
        renameItem = RenameItem(currentName: accountName)
    }

    private func closeBrokerageAccount() {
        Task { await vm.closeBrokerageAccount() }
    }
}

private struct CloseBrokerageAlertModifier: ViewModifier {
    @Bindable var vm: SettingsViewModel

    func body(content: Content) -> some View {
        content.alert(
            L10n.Settings.closeAccountErrorTitle,
            isPresented: $vm.showCloseBrokerageError,
            presenting: vm.closeBrokerageError
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: vm.clearCloseBrokerageError)
        } message: { message in
            Text(message)
        }
    }
}

private struct CloseAccountSuccessBanner: View {
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.sevinoPositive)
            Text(L10n.Settings.closeAccountSuccess)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
        }
        .padding(.horizontal, 16 * scale)
        .padding(.vertical, 10 * scale)
        .modifier(SevinoGlass.popup)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isStaticText)
    }
}

private struct RenameItem: Identifiable {
    let id = UUID()
    let currentName: String
}

private struct AccountRenameSheet: View {
    @Environment(\.popupDismiss) private var popupDismiss

    let item: RenameItem
    let scale: CGFloat
    let onSave: (String) -> Void

    @State private var draftName: String
    @FocusState private var isFocused: Bool

    init(item: RenameItem, scale: CGFloat, onSave: @escaping (String) -> Void) {
        self.item = item
        self.scale = scale
        self.onSave = onSave
        _draftName = State(initialValue: item.currentName)
    }

    private var canSave: Bool {
        let trimmed = draftName.trimmingCharacters(in: .whitespaces)
        return !trimmed.isEmpty && trimmed != item.currentName
    }

    var body: some View {
        SettingsEditPopup(
            title: L10n.Settings.renameTitle,
            scale: scale,
            saveAction: .init(
                label: L10n.Settings.renameSave,
                isEnabled: canSave,
                isLoading: false,
                perform: save
            )
        ) {
            SettingsEditPopupSection(label: L10n.Settings.renameNamePlaceholder, scale: scale) {
                TextField("", text: $draftName)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
                    .textInputAutocapitalization(.words)
                    .submitLabel(.done)
                    .focused($isFocused)
                    .onSubmit { if canSave { save() } }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 12 * scale)
                    .accessibilityLabel(L10n.Settings.renameNamePlaceholder)
            }
        }
        .task { isFocused = true }
    }

    private func save() {
        onSave(draftName.trimmingCharacters(in: .whitespaces))
        popupDismiss()
    }
}

#Preview("Dark") {
    NavigationStack {
        BrokerageSettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        BrokerageSettingsView()
    }
    .preferredColorScheme(.light)
}
