import SwiftUI

struct BrokerageSettingsView: View {
    private static let usdCurrency: Decimal.FormatStyle.Currency = .currency(code: "USD")

    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: SettingsViewModel
    @State private var accountName = L10n.Settings.brokerageAccountNameDefault
    @State private var renameItem: RenameItem?
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
                    navRow(title: L10n.Settings.monthlyStatements, destination: .monthlyStatements)
                    navRow(title: L10n.Settings.taxDocuments, destination: .taxDocuments)
                    navRow(title: L10n.Settings.accountHistory)
                }

                Spacer()

                Button(action: {}) {
                    Text(L10n.Settings.closeAccount)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16 * scale)
                        .contentShape(.rect(cornerRadius: 14 * scale))
                }
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoNegative, cornerRadius: 14 * scale))
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
        .task { await vm.load() }
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
            .sheet(item: $renameItem) { item in
                AccountRenameSheet(item: item, scale: scale) { newName in
                    accountName = newName
                }
                .presentationDetents([.height(180 * scale)])
                .presentationDragIndicator(.visible)
                .presentationBackground(.clear)
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

    private func navRow(title: String, destination: SettingsDestination? = nil) -> some View {
        Group {
            if let destination {
                NavigationLink(value: destination) { navRowLabel(title: title) }
            } else {
                Button(action: {}) { navRowLabel(title: title) }
                    .disabled(true)
            }
        }
    }

    private func navRowLabel(title: String) -> some View {
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

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
        }
    }

    private func copyAccountNumber() {
        guard let number = vm.profile?.brokerage?.accountNumber else { return }
        UIPasteboard.general.string = number
    }

    private func presentRename() {
        renameItem = RenameItem(currentName: accountName)
    }
}

private struct RenameItem: Identifiable {
    let id = UUID()
    let currentName: String
}

private struct AccountRenameSheet: View {
    @Environment(\.dismiss) private var dismiss

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

    var body: some View {
        VStack(spacing: 16 * scale) {
            TextField(L10n.Settings.renameNamePlaceholder, text: $draftName)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 14 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.3), in: .rect(cornerRadius: 12 * scale))
                .focused($isFocused)

            HStack(spacing: 12 * scale) {
                Button(action: dismiss.callAsFunction) {
                    Text(L10n.Settings.renameCancel)
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12 * scale)
                }
                .modifier(SevinoGlass.card)

                Button(action: save) {
                    Text(L10n.Settings.renameSave)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12 * scale)
                }
                .modifier(SevinoGlass.card)
                .disabled(draftName.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20 * scale)
        .modifier(SevinoGlass.card)
        .padding(.horizontal, 12 * scale)
        .task { isFocused = true }
    }

    private func save() {
        onSave(draftName.trimmingCharacters(in: .whitespaces))
        dismiss()
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
