import SwiftUI

struct AlpacaSetupCompleteView: View {
    let scale: CGFloat
    let userName: String
    let onSubmit: () async throws -> Void
    let onContinue: () -> Void

    @State private var showLoading = false
    @State private var typedHeading = ""
    @State private var typedBody = ""
    @State private var typedCta = ""
    @State private var showButton = false
    @State private var submitFailed = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
                        .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
                }
                .buttonStyle(.plain)
                .modifier(SevinoGlass.tintedButton(tint: Color.onboardingButtonActive))
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

        // Submit KYC to Alpaca during the loading state
        do {
            try await onSubmit()
        } catch {
            print("[AlpacaSetup] Submit failed: \(error)")
            submitFailed = true
        }

        showLoading = false

        if submitFailed {
            typedHeading = L10n.Onboarding.alpacaSubmitErrorHeading
            typedBody = L10n.Onboarding.alpacaSubmitErrorBody
            try? await Task.sleep(for: .milliseconds(300))
            withAnimation(.easeOut(duration: 0.3)) { showButton = true }
            return
        }

        await TypewriterAnimation.typeOut(L10n.Onboarding.alpacaCompleteHeading(userName), reduceMotion: reduceMotion) { typedHeading = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await TypewriterAnimation.typeOut(L10n.Onboarding.alpacaCompleteBody, reduceMotion: reduceMotion) { typedBody = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await TypewriterAnimation.typeOut(L10n.Onboarding.alpacaCompleteCta, reduceMotion: reduceMotion) { typedCta = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showButton = true }
    }
}

#Preview {
    AlpacaSetupCompleteView(scale: 1, userName: "Riley", onSubmit: {}, onContinue: {})
}
