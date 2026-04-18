import SwiftUI

struct OnboardingDisclaimerView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: () -> Void

    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var typed3 = ""
    @State private var showButton = false

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16 * scale) {
                    if showPrompt {
                        HStack {
                            Spacer()
                            Text(userPromptText)
                                .font(.system(size: 15 * scale))
                                .foregroundStyle(Color.welcomeText)
                                .padding(.horizontal, 16 * scale)
                                .padding(.vertical, 10 * scale)
                                .background(
                                    Color.saturnGreyAccent.opacity(0.4),
                                    in: RoundedRectangle(cornerRadius: 16 * scale)
                                )
                        }
                        .transition(.opacity.combined(with: .offset(y: 10)))
                    }

                    VStack(alignment: .leading, spacing: 16 * scale) {
                        if !typed1.isEmpty {
                            Text(typed1)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.welcomeText)
                        }
                        if !typed2.isEmpty {
                            Text(typed2)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.welcomeText)
                        }
                        if !typed3.isEmpty {
                            Text(typed3)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.welcomeText)
                        }
                    }
                }
                .padding(.horizontal, 20 * scale)
                .padding(.top, 16 * scale)
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)

            if showButton {
                Button(action: onContinue) {
                    Text(L10n.Onboarding.disclaimerButton)
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


    private func animateIn() async {
        let line1 = L10n.Onboarding.disclaimerResponse1
        let line2 = L10n.Onboarding.disclaimerResponse2
        let line3 = L10n.Onboarding.disclaimerResponse3

        guard animate else {
            showPrompt = true
            typed1 = line1
            typed2 = line2
            typed3 = line3
            showButton = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(line1) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(line2) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(line3) { typed3 = $0 }
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
    OnboardingDisclaimerView(
        scale: 1,
        userPromptText: "I've never really invested",
        animate: true,
        onContinue: {}
    )
    .background(Color.black)
    .preferredColorScheme(.dark)
}
