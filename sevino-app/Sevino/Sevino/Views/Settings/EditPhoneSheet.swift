import SwiftUI

/// Popup card presented from PersonalInfoSettingsView for editing the user's
/// phone number. Client-side validation is deliberately loose — Alpaca enforces
/// E.164 on the backend — but we block obviously bad input.
struct EditPhoneSheet: View {
    @Environment(\.popupDismiss) private var popupDismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: EditProfileViewModel
    @State private var phone: String
    @State private var baseScale: CGFloat = 1

    @FocusState private var isFocused: Bool

    private let initialPhone: String
    private let onSaved: () -> Void

    private var scale: CGFloat { baseScale * textMultiplier }

    private var canSave: Bool {
        EditProfileViewModel.isValidPhone(phone) && phone != initialPhone
    }

    init(
        currentPhone: String?,
        vm: EditProfileViewModel = EditProfileViewModel(),
        onSaved: @escaping () -> Void = {}
    ) {
        _vm = State(initialValue: vm)
        let value = currentPhone ?? ""
        _phone = State(initialValue: value)
        initialPhone = value
        self.onSaved = onSaved
    }

    var body: some View {
        SettingsEditPopup(
            title: L10n.Settings.editPhoneTitle,
            scale: scale,
            saveAction: .init(
                label: L10n.Settings.editProfileSave,
                isEnabled: canSave && !vm.didSave,
                isLoading: vm.isLoading,
                perform: save
            )
        ) {
            SettingsEditPopupSection(label: L10n.Settings.editPhoneLabel, scale: scale) {
                TextField("", text: $phone)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.sevinoSecondary)
                    .textContentType(.telephoneNumber)
                    .keyboardType(.phonePad)
                    .submitLabel(.done)
                    .focused($isFocused)
                    .onSubmit { isFocused = false }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 12 * scale)
                    .accessibilityLabel(L10n.Settings.editPhoneLabel)
            }

            if let error = vm.error {
                Text(error)
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoNegative)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .task { isFocused = true }
        .task(id: vm.didSave, handleDidSaveChange)
    }

    private func handleDidSaveChange() async {
        guard vm.didSave else { return }
        onSaved()
        popupDismiss()
    }

    private func save() {
        isFocused = false
        Task { await vm.savePhone(phone) }
    }
}

#if DEBUG
#Preview("Edit phone") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditPhoneSheet(
                currentPhone: "+11234567890",
                vm: EditProfileViewModel(service: PreviewLoadedSettingsService())
            )
        }
        .preferredColorScheme(.dark)
}
#endif
