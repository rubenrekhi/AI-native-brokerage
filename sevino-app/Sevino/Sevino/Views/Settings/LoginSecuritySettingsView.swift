import SwiftUI

struct LoginSecuritySettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var showDeleteConfirmation = false
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            VStack(spacing: 0) {
                navRow(title: L10n.Settings.email)
                navRow(title: L10n.Settings.changePassword)
                navRow(title: L10n.Settings.manageFaceId)
                navRow(title: L10n.Settings.activeSessions)
            }

            Spacer()

            Button(action: { showDeleteConfirmation = true }) {
                Text(L10n.Settings.deleteAccount)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16 * scale)
            }
            .modifier(SevinoGlass.tintedButton(tint: Color.sevinoNegative, cornerRadius: 14 * scale))
            .confirmationDialog(L10n.Settings.deleteConfirmTitle, isPresented: $showDeleteConfirmation) {
                Button(L10n.Settings.deleteConfirmAction, role: .destructive, action: {})
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
        SettingsHeaderView(title: L10n.Settings.loginSecurity, scale: scale, onBack: { dismiss() })
    }

    private func navRow(title: String) -> some View {
        Button(action: {}) {
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
        .disabled(true)
    }
}

#Preview("Dark") {
    NavigationStack {
        LoginSecuritySettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        LoginSecuritySettingsView()
    }
    .preferredColorScheme(.light)
}
