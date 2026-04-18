import SwiftUI

struct AlpacaSetupIntroView: View {
    let scale: CGFloat
    let userName: String
    let animate: Bool
    let onContinue: () -> Void

    @State private var typedHeading = ""
    @State private var typedBody = ""
    @State private var typedDisclaimer = ""
    @State private var showButton = false

    var body: some View {
        VStack(spacing: 0) {
            Image("logo_white")
                .resizable()
                .scaledToFit()
                .frame(height: 36 * scale)
                .accessibilityLabel(L10n.General.appName)
                .padding(.top, 16 * scale)

            ScrollView {
                VStack(alignment: .leading, spacing: 20 * scale) {
                    if !typedHeading.isEmpty {
                        Text(typedHeading)
                            .font(.system(size: 22 * scale, weight: .light))
                            .foregroundStyle(Color.welcomeText)
                    }

                    if !typedBody.isEmpty {
                        Text(typedBody)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.welcomeTextSecondary)
                    }

                    if !typedDisclaimer.isEmpty {
                        Text(typedDisclaimer)
                            .font(.system(size: 16 * scale, weight: .semibold))
                            .foregroundStyle(Color.welcomeText)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 24 * scale)
                .padding(.top, 24 * scale)
            }
            .scrollIndicators(.hidden)

            Spacer()

            if showButton {
                Button(action: onContinue) {
                    Text(L10n.Onboarding.alpacaIntroButton)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeText)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                }
                .buttonStyle(.plain)
                .modifier(SaturnGlass.tintedButton(tint: Color.onboardingButtonActive))
                .padding(.horizontal, 32 * scale)
                .padding(.bottom, 16 * scale)
                .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showButton)
        .background { OnboardingBackgroundView() }
        .task { await animateIn() }
    }

    private func animateIn() async {
        guard animate else {
            typedHeading = L10n.Onboarding.alpacaIntroHeading(userName)
            typedBody = L10n.Onboarding.alpacaIntroBody
            typedDisclaimer = L10n.Onboarding.alpacaIntroDisclaimer
            showButton = true
            return
        }
        try? await Task.sleep(for: .milliseconds(400))
        await typeOut(L10n.Onboarding.alpacaIntroHeading(userName)) { typedHeading = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaIntroBody) { typedBody = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaIntroDisclaimer) { typedDisclaimer = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showButton = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        guard !text.isEmpty else { return }
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    AlpacaSetupIntroView(scale: 1, userName: "Riley", animate: true, onContinue: {})
}
