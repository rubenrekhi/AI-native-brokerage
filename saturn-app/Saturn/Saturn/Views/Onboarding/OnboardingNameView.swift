import SwiftUI

struct OnboardingNameView: View {
    let scale: CGFloat
    let animate: Bool
    let onContinue: (String) -> Void

    @State private var name = ""
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var showInput = false

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 16 * scale) {
                // User prompt bubble
                if showPrompt {
                    HStack {
                        Spacer()
                        Text(L10n.Onboarding.nameUserPrompt)
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

                // Bot response — typed char by char
                VStack(alignment: .leading, spacing: 12 * scale) {
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
                }
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 16 * scale)

            Spacer()

            if showInput {
                chatInput
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showInput)
        .task { await animateIn() }
    }

    // MARK: - Chat Input

    private var chatInput: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            TextField(
                "",
                text: $name,
                prompt: Text(L10n.Onboarding.namePlaceholder)
                    .foregroundStyle(Color.welcomeTextDimmed)
            )
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.welcomeText)
            .textInputAutocapitalization(.words)
            .submitLabel(.send)
            .onSubmit(submit)

            HStack {
                Image(systemName: "mic")
                    .font(.system(size: 18 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .accessibilityHidden(true)
                Spacer()
                Button(action: submit) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 28 * scale))
                        .foregroundStyle(isNameValid ? Color.welcomeText : Color.welcomeTextDimmed)
                }
                .accessibilityLabel("Submit")
                .disabled(!isNameValid)
            }
        }
        .padding(14 * scale)
        .modifier(SaturnGlass.nav)
        .padding(.horizontal, 8 * scale)
        .padding(.bottom, 16 * scale)
    }

    private var isNameValid: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty
    }

    private func submit() {
        guard isNameValid else { return }
        onContinue(name.trimmingCharacters(in: .whitespaces))
    }

    // MARK: - Animation

    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.nameResponse1
            typed2 = L10n.Onboarding.nameResponse2
            showInput = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.nameResponse1) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.nameResponse2) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showInput = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    OnboardingNameView(scale: 1, animate: true, onContinue: { _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
