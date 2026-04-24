import SwiftUI

struct ChangePasswordView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @Bindable var vm: ChangePasswordViewModel
    @State private var baseScale: CGFloat = 1
    @FocusState private var focusedField: ChangePasswordField?

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        ScrollView {
            SevinoGlassContainer {
                VStack(spacing: 0) {
                    SettingsHeaderView(title: L10n.Settings.changePassword, scale: scale, onBack: { dismiss() })
                        .padding(.bottom, 24 * scale)

                    subtitle
                        .padding(.bottom, 20 * scale)

                    passwordFields

                    if !vm.newPassword.isEmpty {
                        PasswordRequirementsView(password: vm.newPassword, scale: scale)
                            .padding(.horizontal, 4 * scale)
                            .padding(.top, 12 * scale)
                    }

                    if let error = vm.error {
                        Text(error)
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(Color.sevinoNegative)
                            .multilineTextAlignment(.center)
                            .padding(.top, 16 * scale)
                            .padding(.horizontal, 8 * scale)
                    }

                    ChangePasswordSubmitButton(vm: vm, scale: scale, onTap: submit)
                        .padding(.top, 24 * scale)
                }
                .padding(.horizontal, 20 * scale)
                .padding(.top, 12 * scale)
                .padding(.bottom, 24 * scale)
            }
        }
        .scrollIndicators(.hidden)
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
        .overlay(alignment: .top) {
            if vm.didSucceed {
                ChangePasswordSuccessBanner(scale: scale)
                    .padding(.top, 8 * scale)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.25), value: vm.didSucceed)
        .task(id: vm.didSucceed) {
            guard vm.didSucceed else { return }
            try? await Task.sleep(for: .milliseconds(1200))
            guard !Task.isCancelled else { return }
            dismiss()
        }
    }

    private var subtitle: some View {
        Text(L10n.Settings.changePasswordSubtitle)
            .font(.system(size: 14 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var passwordFields: some View {
        VStack(spacing: 16 * scale) {
            ChangePasswordFieldRow(
                label: L10n.Settings.currentPasswordLabel,
                text: $vm.currentPassword,
                contentType: .password,
                submitLabel: .next,
                focus: .current,
                focusedField: $focusedField,
                scale: scale,
                onSubmit: { focusedField = .new }
            )
            ChangePasswordFieldRow(
                label: L10n.Settings.newPasswordLabel,
                text: $vm.newPassword,
                contentType: .newPassword,
                submitLabel: .next,
                focus: .new,
                focusedField: $focusedField,
                scale: scale,
                onSubmit: { focusedField = .confirm }
            )
            ChangePasswordFieldRow(
                label: L10n.Settings.confirmPasswordLabel,
                text: $vm.confirmPassword,
                contentType: .newPassword,
                submitLabel: .done,
                focus: .confirm,
                focusedField: $focusedField,
                scale: scale,
                onSubmit: { focusedField = nil }
            )
        }
    }

    private func submit() {
        focusedField = nil
        Task { await vm.changePassword() }
    }
}

enum ChangePasswordField: Hashable { case current, new, confirm }

private struct ChangePasswordFieldRow: View {
    let label: String
    @Binding var text: String
    let contentType: UITextContentType
    let submitLabel: SubmitLabel
    let focus: ChangePasswordField
    var focusedField: FocusState<ChangePasswordField?>.Binding
    let scale: CGFloat
    let onSubmit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(label)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            SecureField("", text: $text)
                .textContentType(contentType)
                .submitLabel(submitLabel)
                .focused(focusedField, equals: focus)
                .onSubmit(onSubmit)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 14 * scale)
                .modifier(SevinoGlass.card)
                .accessibilityLabel(label)
        }
    }
}

private struct ChangePasswordSubmitButton: View {
    @Bindable var vm: ChangePasswordViewModel
    let scale: CGFloat
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            Group {
                if vm.isLoading {
                    ProgressView()
                        .tint(Color.sevinoSecondary)
                } else {
                    Text(L10n.Settings.changePasswordCta)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14 * scale)
            .contentShape(.rect(cornerRadius: 14 * scale))
        }
        .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 14 * scale))
        .disabled(!vm.isValid || vm.isLoading || vm.didSucceed)
        .opacity(vm.isValid ? 1 : 0.6)
    }
}

private struct ChangePasswordSuccessBanner: View {
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.sevinoPositive)
            Text(L10n.Settings.changePasswordSuccess)
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

#Preview("Dark") {
    NavigationStack {
        ChangePasswordView(vm: ChangePasswordViewModel(authService: PreviewAuthService()))
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        ChangePasswordView(vm: ChangePasswordViewModel(authService: PreviewAuthService()))
    }
    .preferredColorScheme(.light)
}
