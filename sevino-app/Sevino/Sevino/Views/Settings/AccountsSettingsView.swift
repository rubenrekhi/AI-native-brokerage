import SwiftUI

struct AccountsSettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    // TODO: Replace with real status from ViewModel
    private let kycStatus = KYCStatus.submitted

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.bottom, 24 * scale)

            navLinkRow(title: L10n.Settings.brokerage, destination: .brokerage)
            navLinkRow(title: L10n.Settings.linkedAccounts, destination: .linkedAccounts)
            settingsRow(title: L10n.Settings.kycStatus, trailing: .kycBadge(kycStatus))

            Spacer()
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
        SettingsHeaderView(title: L10n.Settings.accounts, scale: scale, onBack: { dismiss() })
    }

    private func navLinkRow(title: String, destination: SettingsDestination) -> some View {
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

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
    }

    private func settingsRow(title: String, trailing: RowTrailing) -> some View {
        Button(action: {}) {
            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    switch trailing {
                    case .chevron:
                        Image(systemName: "chevron.right")
                            .font(.system(size: 13 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoGreyContrast)
                            .accessibilityHidden(true)
                    case .kycBadge(let status):
                        Text(status.label)
                            .font(.system(size: 12 * scale, weight: .semibold))
                            .foregroundStyle(status.color)
                            .padding(.horizontal, 10 * scale)
                            .padding(.vertical, 4 * scale)
                            .background(status.color.opacity(0.15), in: .rect(cornerRadius: 6 * scale))
                    }
                }
                .padding(.vertical, 16 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
        .disabled(true)
    }
}

private enum RowTrailing {
    case chevron
    case kycBadge(KYCStatus)
}

#Preview("Dark") {
    NavigationStack {
        AccountsSettingsView()
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    NavigationStack {
        AccountsSettingsView()
    }
    .preferredColorScheme(.light)
}
