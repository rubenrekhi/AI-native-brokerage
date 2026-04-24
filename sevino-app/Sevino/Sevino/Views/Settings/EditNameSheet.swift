import SwiftUI

/// Sheet presented from PersonalInfoSettingsView for editing the user's legal
/// name. First and last are required; middle is optional.
struct EditNameSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: EditProfileViewModel
    @State private var firstName: String
    @State private var middleName: String
    @State private var lastName: String
    @State private var baseScale: CGFloat = 1

    @FocusState private var focusedField: Field?

    private enum Field: Hashable { case first, middle, last }

    private let onSaved: () -> Void

    private var scale: CGFloat { baseScale * textMultiplier }

    private var canSave: Bool {
        !firstName.trimmingCharacters(in: .whitespaces).isEmpty
            && !lastName.trimmingCharacters(in: .whitespaces).isEmpty
    }

    init(
        currentFirstName: String?,
        currentMiddleName: String?,
        currentLastName: String?,
        vm: EditProfileViewModel = EditProfileViewModel(),
        onSaved: @escaping () -> Void = {}
    ) {
        _vm = State(initialValue: vm)
        _firstName = State(initialValue: currentFirstName ?? "")
        _middleName = State(initialValue: currentMiddleName ?? "")
        _lastName = State(initialValue: currentLastName ?? "")
        self.onSaved = onSaved
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 16 * scale) {
                Text(L10n.Settings.editNameTitle)
                    .font(.system(size: 17 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                field(label: L10n.Settings.editNameFirstLabel, text: $firstName, focus: .first, next: .middle)
                field(label: L10n.Settings.editNameMiddleLabel, text: $middleName, focus: .middle, next: .last)
                field(label: L10n.Settings.editNameLastLabel, text: $lastName, focus: .last, next: nil)

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
        .task { focusedField = .first }
        .task(id: vm.didSave, handleDidSaveChange)
    }

    private func handleDidSaveChange() async {
        guard vm.didSave else { return }
        onSaved()
        try? await Task.sleep(for: .milliseconds(400))
        guard !Task.isCancelled else { return }
        dismiss()
    }

    private func field(label: String, text: Binding<String>, focus: Field, next: Field?) -> some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text(label)
                .font(.system(size: 12 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            TextField("", text: text)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .textContentType(contentType(for: focus))
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled()
                .submitLabel(next == nil ? .done : .next)
                .focused($focusedField, equals: focus)
                .onSubmit {
                    if let next { focusedField = next } else { focusedField = nil }
                }
                .padding(.horizontal, 14 * scale)
                .padding(.vertical, 12 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.3), in: .rect(cornerRadius: 10 * scale))
                .accessibilityLabel(label)
        }
    }

    private func contentType(for field: Field) -> UITextContentType {
        switch field {
        case .first: .givenName
        case .middle: .middleName
        case .last: .familyName
        }
    }

    private func save() {
        focusedField = nil
        Task {
            await vm.saveName(
                first: firstName,
                middle: middleName.isEmpty ? nil : middleName,
                last: lastName
            )
        }
    }
}

#if DEBUG
#Preview("Edit name") {
    EditNameSheet(
        currentFirstName: "Riley",
        currentMiddleName: nil,
        currentLastName: "Ready",
        vm: EditProfileViewModel(service: PreviewLoadedSettingsService())
    )
    .preferredColorScheme(.dark)
}
#endif
