import SwiftUI

struct AlpacaSetupCompleteView: View {
    let scale: CGFloat
    let userName: String
    let onContinue: () -> Void

    @State private var showLoading = false
    @State private var typedHeading = ""
    @State private var typedBody = ""
    @State private var typedCta = ""
    @State private var showButton = false

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16 * scale) {
                    if showLoading {
                        HStack(spacing: 8 * scale) {
                            Text(L10n.Onboarding.alpacaCompleteLoading)
                                .font(.system(size: 14 * scale))
                                .foregroundStyle(Color.welcomeTextMuted)
                            ProgressView()
                                .tint(Color.welcomeTextMuted)
                                .scaleEffect(0.8)
                        }
                        .transition(.opacity)
                    }

                    if !typedHeading.isEmpty {
                        Text(typedHeading)
                            .font(.system(size: 24 * scale, weight: .light))
                            .foregroundStyle(Color.welcomeText)
                    }

                    if !typedBody.isEmpty {
                        Text(typedBody)
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
                .padding(.horizontal, 24 * scale)
                .padding(.top, 24 * scale)
            }
            .scrollIndicators(.hidden)

            Spacer()

            if showButton {
                Button(action: onContinue) {
                    Text(L10n.Onboarding.alpacaCompleteButton)
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
        .animation(.easeOut(duration: 0.3), value: showLoading)
        .animation(.easeOut(duration: 0.3), value: showButton)
        .task { await animateIn() }
    }

    private func animateIn() async {
        try? await Task.sleep(for: .milliseconds(400))
        showLoading = true

        try? await Task.sleep(for: .milliseconds(2000))

        await typeOut(L10n.Onboarding.alpacaCompleteHeading(userName)) { typedHeading = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaCompleteBody) { typedBody = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaCompleteCta) { typedCta = $0 }
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
    AlpacaSetupCompleteView(scale: 1, userName: "Riley", onContinue: {})
}
