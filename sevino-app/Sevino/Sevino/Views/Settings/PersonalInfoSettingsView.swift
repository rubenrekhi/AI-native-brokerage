import SwiftUI

struct PersonalInfoSettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    // TODO: Replace with real user data from ViewModel
    private let userName = "Ready Riley"
    private let userTier = "Free Tier"
    private let userSince = "3 months, 2 weeks, 2 days"
    private let userEmail = "ready.riley@sevino.ai"
    private let userPhone = "+1 (123) 456 7890"
    private let userAddress = "123 Invest Circle, 44110, Cleveland, OH"
    private let userRiskTolerance = "Aggressive"

    private var initials: String {
        userName.split(separator: " ").prefix(2).compactMap { $0.first.map(String.init) }.joined()
    }

    private var scale: CGFloat { UIScreen.main.bounds.width / 393 * textMultiplier }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                profileCard
                    .padding(.bottom, 24 * scale)

                VStack(spacing: 0) {
                    infoRow(title: L10n.Settings.nameDetails)
                    infoRowWithValue(title: L10n.Settings.emailLabel, value: userEmail)
                    infoRowWithValue(title: L10n.Settings.phoneLabel, value: userPhone)
                    infoRowWithValue(title: L10n.Settings.mailingAddress, value: userAddress)
                    infoRowWithValue(title: L10n.Settings.riskTolerance, value: userRiskTolerance)
                }
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .navigationBarBackButtonHidden()
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.personalInfo, scale: scale, onBack: { dismiss() })
    }

    private var profileCard: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            HStack(spacing: 12 * scale) {
                Text(initials)
                    .font(.system(size: 18 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoPrimary)
                    .frame(width: 48 * scale, height: 48 * scale)
                    .background(
                        LinearGradient(
                            colors: [Color.sevinoAvatarPurple, Color.sevinoInfo],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        in: .circle
                    )

                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(userName)
                        .font(.system(size: 16 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)

                    Text(userTier)
                        .font(.system(size: 11 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoWarning)
                        .padding(.horizontal, 8 * scale)
                        .padding(.vertical, 3 * scale)
                        .background(Color.sevinoWarning.opacity(0.15), in: .rect(cornerRadius: 4 * scale))
                }
            }

            Text(L10n.Settings.usingSevino(userSince))
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }

    private func infoRow(title: String) -> some View {
        Button(action: {}) {
            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(.system(size: 15 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    Image(systemName: "pencil.line")
                        .font(.system(size: 15 * scale, weight: .medium))
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

    private func infoRowWithValue(title: String, value: String) -> some View {
        Button(action: {}) {
            VStack(spacing: 0) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4 * scale) {
                        Text(title)
                            .font(.system(size: 15 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)

                        Text(value)
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(Color.sevinoGreyContrast)
                    }

                    Spacer()

                    Image(systemName: "pencil.line")
                        .font(.system(size: 15 * scale, weight: .medium))
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
        PersonalInfoSettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        PersonalInfoSettingsView()
    }
    .preferredColorScheme(.light)
}
