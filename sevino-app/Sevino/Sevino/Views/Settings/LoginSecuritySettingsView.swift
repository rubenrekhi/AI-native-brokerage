import SwiftUI

struct LoginSecuritySettingsView: View {
    @Bindable var viewModel: SettingsViewModel

    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var showDeleteConfirmation = false
    @State private var showEmailPopup = false
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            VStack(spacing: 0) {
                buttonRow(title: L10n.Settings.email) { showEmailPopup = true }
                navLinkRow(title: L10n.Settings.changePassword, destination: .changePassword)
                navLinkRow(title: L10n.Settings.manageFaceId, destination: .manageFaceId)
                comingSoonRow(title: L10n.Settings.activeSessions)
            }

            Spacer()

            Button(action: { showDeleteConfirmation = true }) {
                deleteLabel
            }
            .modifier(SevinoGlass.tintedButton(tint: Color.sevinoNegative, cornerRadius: 14 * scale))
            .disabled(viewModel.isDeletingAccount)
            .confirmationDialog(L10n.Settings.deleteConfirmTitle, isPresented: $showDeleteConfirmation) {
                Button(L10n.Settings.deleteConfirmAction, role: .destructive, action: deleteAccount)
            } message: {
                Text(L10n.Settings.deleteConfirmMessage)
            }
            .padding(.bottom, 16 * scale)
        }
        .padding(.horizontal, 20 * scale)
        .padding(.top, 12 * scale)
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
            L10n.Settings.deleteErrorTitle,
            isPresented: $viewModel.showDeleteError,
            presenting: viewModel.deleteError
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: viewModel.clearDeleteError)
        } message: { message in
            Text(message)
        }
        .popupCard(isPresented: $showEmailPopup) {
            EditEmailSheet(email: viewModel.displayEmail)
        }
        .task {
            if viewModel.profile == nil {
                await viewModel.load()
            }
        }
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.loginSecurity, scale: scale, onBack: { dismiss() })
    }

    @ViewBuilder
    private var deleteLabel: some View {
        if viewModel.isDeletingAccount {
            ProgressView()
                .tint(Color.sevinoSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16 * scale)
                .contentShape(.rect(cornerRadius: 14 * scale))
        } else {
            Text(L10n.Settings.deleteAccount)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16 * scale)
                .contentShape(.rect(cornerRadius: 14 * scale))
        }
    }

    private func navLinkRow(title: String, destination: SettingsDestination) -> some View {
        NavigationLink(value: destination) {
            rowContent(title: title)
        }
        .buttonStyle(.plain)
    }

    private func buttonRow(title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            rowContent(title: title)
        }
        .buttonStyle(.plain)
    }

    private func comingSoonRow(title: String) -> some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(title)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)

                    Text(L10n.Settings.comingSoon)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast.opacity(0.7))
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast.opacity(0.5))
                    .accessibilityHidden(true)
            }
            .padding(.vertical, 16 * scale)

            Divider()
                .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
        }
        .accessibilityElement(children: .combine)
    }

    private func rowContent(title: String) -> some View {
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

    private func deleteAccount() {
        Task { await viewModel.deleteAccount() }
    }
}

#Preview("Dark") {
    NavigationStack {
        LoginSecuritySettingsView(viewModel: SettingsViewModel())
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        LoginSecuritySettingsView(viewModel: SettingsViewModel())
    }
    .preferredColorScheme(.light)
}
