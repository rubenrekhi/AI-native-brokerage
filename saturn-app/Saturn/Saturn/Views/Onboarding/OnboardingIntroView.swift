import SwiftUI

struct OnboardingIntroView: View {
    let scale: CGFloat
    let animate: Bool
    let onContinue: () -> Void

    @State private var typedTitle = ""
    @State private var typedBody1 = ""
    @State private var typedBody2 = ""
    @State private var typedBody3 = ""
    @State private var typedCta = ""
    @State private var showButton = false

    var body: some View {
        VStack(spacing: 0) {
            Spacer()
                .frame(height: 50 * scale)

            VStack(alignment: .leading, spacing: 20 * scale) {
                if !typedTitle.isEmpty {
                    Text(typedTitle)
                        .font(.system(size: 28 * scale, weight: .bold))
                        .foregroundStyle(Color.welcomeText)
                }
                if !typedBody1.isEmpty {
                    Text(typedBody1)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.welcomeTextSecondary)
                }
                if !typedBody2.isEmpty {
                    Text(typedBody2)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.welcomeTextSecondary)
                }
                if !typedBody3.isEmpty {
                    Text(typedBody3)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.welcomeTextSecondary)
                }
                if !typedCta.isEmpty {
                    Text(typedCta)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeText)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 32 * scale)

            Spacer()

            if showButton {
                Button(action: onContinue) {
                    Text(L10n.Onboarding.introButton)
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
        .task { await animateIn() }
    }

    // MARK: - Animation

    private func animateIn() async {
        guard animate else {
            typedTitle = L10n.Onboarding.introTitle
            typedBody1 = L10n.Onboarding.introBody1
            typedBody2 = L10n.Onboarding.introBody2
            typedBody3 = L10n.Onboarding.introBody3
            typedCta = L10n.Onboarding.introCta
            showButton = true
            return
        }
        try? await Task.sleep(for: .milliseconds(400))
        await typeOut(L10n.Onboarding.introTitle) { typedTitle = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.introBody1) { typedBody1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.introBody2) { typedBody2 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.introBody3) { typedBody3 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.introCta) { typedCta = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showButton = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    ZStack {
        OnboardingBackgroundView()
        OnboardingIntroView(scale: 1, animate: true, onContinue: {})
    }
    .preferredColorScheme(.dark)
}
