import SwiftUI

/// Sheet presented from PersonalInfoSettingsView for editing the user's phone
/// number. Client-side validation is deliberately loose — Alpaca enforces
/// E.164 on the backend — but we block obviously bad input.
struct EditPhoneSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: EditProfileViewModel
    @State private var phone: String
    @State private var baseScale: CGFloat = 1

    @FocusState private var isFocused: Bool

    private let onSaved: () -> Void

    private var scale: CGFloat { baseScale * textMultiplier }

    private var canSave: Bool {
        EditProfileViewModel.isValidPhone(phone)
    }

    init(
        currentPhone: String?,
        vm: EditProfileViewModel = EditProfileViewModel(),
        onSaved: @escaping () -> Void = {}
    ) {
        _vm = State(initialValue: vm)
        _phone = State(initialValue: currentPhone ?? "")
        self.onSaved = onSaved
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 16 * scale) {
                Text(L10n.Settings.editPhoneTitle)
                    .font(.system(size: 17 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                VStack(alignment: .leading, spacing: 6 * scale) {
                    Text(L10n.Settings.editPhoneLabel)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)

                    TextField("", text: $phone)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)
                        .textContentType(.telephoneNumber)
                        .keyboardType(.phonePad)
                        .submitLabel(.done)
                        .focused($isFocused)
                        .onSubmit { isFocused = false }
                        .padding(.horizontal, 14 * scale)
                        .padding(.vertical, 12 * scale)
                        .background(Color.sevinoGreyAccent.opacity(0.3), in: .rect(cornerRadius: 10 * scale))
                        .accessibilityLabel(L10n.Settings.editPhoneLabel)
                }

                if let error = vm.error {
                    Text(error)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoNegative)
                        .multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                HStack(spacing: 12 * scale) {
                    Button(action: dismiss.callAsFunction) {
                        Text(L10n.Settings.editProfileCancel)
                            .font(.system(size: 15 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12 * scale)
                    }
                    .modifier(SevinoGlass.card)
                    .disabled(vm.isLoading)

                    Button(action: save) {
                        ZStack {
                            Text(L10n.Settings.editProfileSave)
                                .font(.system(size: 15 * scale, weight: .semibold))
                                .foregroundStyle(Color.sevinoSecondary)
                                .opacity(vm.isLoading ? 0 : 1)
                            if vm.isLoading {
                                ProgressView().tint(Color.sevinoSecondary)
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12 * scale)
                    }
                    .modifier(SevinoGlass.card)
                    .disabled(!canSave || vm.isLoading || vm.didSave)
                }
            }
            .padding(20 * scale)
            .modifier(SevinoGlass.card)
            .padding(.horizontal, 12 * scale)
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
        try? await Task.sleep(for: .milliseconds(400))
        guard !Task.isCancelled else { return }
        dismiss()
    }

    private func save() {
        isFocused = false
        Task { await vm.savePhone(phone) }
    }
}

#if DEBUG
#Preview("Edit phone") {
    EditPhoneSheet(
        currentPhone: "+11234567890",
        vm: EditProfileViewModel(service: PreviewLoadedSettingsService())
    )
    .preferredColorScheme(.dark)
}
#endif
