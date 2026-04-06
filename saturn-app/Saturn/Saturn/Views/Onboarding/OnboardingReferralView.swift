import SwiftUI

struct OnboardingReferralView: View {
    let scale: CGFloat
    let userName: String
    let animate: Bool
    let onContinue: (_ source: String, _ extra: String?) -> Void

    @State private var selectedSource: String?
    @State private var extraText = ""
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var typed3 = ""
    @State private var showOptions = false

    private let sources = [
        L10n.Onboarding.referralTiktok, L10n.Onboarding.referralInstagram,
        L10n.Onboarding.referralTwitter, L10n.Onboarding.referralFriend,
        L10n.Onboarding.referralGoogle, L10n.Onboarding.referralReddit,
        L10n.Onboarding.referralAiTool, L10n.Onboarding.referralLinkedin,
        L10n.Onboarding.referralArticle, L10n.Onboarding.referralOther,
    ]

    private var needsExtraText: Bool {
        selectedSource == L10n.Onboarding.referralFriend || selectedSource == L10n.Onboarding.referralOther
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16 * scale) {
                    if showPrompt {
                        userPrompt
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
                        if !typed3.isEmpty {
                            Text(typed3)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.welcomeText)
                        }
                    }

                    // Options
                    if showOptions {
                        optionsGrid
                            .transition(.opacity.combined(with: .offset(y: 16)))

                        if needsExtraText {
                            extraTextField
                                .transition(.opacity.combined(with: .offset(y: 8)))
                        }
                    }
                }
                .padding(.horizontal, 20 * scale)
                .padding(.top, 16 * scale)
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)

            if showOptions {
                continueButton
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showOptions)
        .task { await animateIn() }
    }

    // MARK: - User Prompt

    private var userPrompt: some View {
        HStack {
            Spacer()
            Text(userName)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 10 * scale)
                .background(
                    Color.saturnGreyAccent.opacity(0.4),
                    in: RoundedRectangle(cornerRadius: 16 * scale)
                )
        }
    }

    // MARK: - Options Grid

    private var optionsGrid: some View {
        LazyVGrid(
            columns: [
                GridItem(.flexible(), spacing: 12 * scale),
                GridItem(.flexible(), spacing: 12 * scale),
            ],
            spacing: 12 * scale
        ) {
            ForEach(sources, id: \.self) { source in
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        selectedSource = source
                    }
                    if !needsExtraText { extraText = "" }
                } label: {
                    Text(source)
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                        .padding(.horizontal, 16 * scale)
                        .modifier(SaturnGlass.tintedButton(
                            tint: selectedSource == source
                                ? Color.saturnAccent
                                : Color.clear,
                            cornerRadius: 16
                        ))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.top, 8 * scale)
    }

    // MARK: - Extra Text Field

    private var extraTextField: some View {
        TextField(
            "",
            text: $extraText,
            prompt: Text(
                selectedSource == L10n.Onboarding.referralFriend
                    ? L10n.Onboarding.referralFriendPlaceholder
                    : L10n.Onboarding.referralOtherPlaceholder
            )
            .foregroundStyle(Color.welcomeTextDimmed),
            axis: .vertical
        )
        .font(.system(size: 15 * scale))
        .foregroundStyle(Color.welcomeText)
        .lineLimit(2...4)
        .padding(14 * scale)
        .modifier(SaturnGlass.nav)
    }

    // MARK: - Continue Button

    private var continueButton: some View {
        Button { onContinue(selectedSource ?? "", extraText.isEmpty ? nil : extraText) } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SaturnGlass.tintedButton(
            tint: selectedSource != nil ? Color.onboardingButtonActive : Color.onboardingButtonInactive
        ))
        .disabled(selectedSource == nil)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }

    // MARK: - Animation

    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.referralResponse1(userName)
            typed2 = L10n.Onboarding.referralResponse2
            typed3 = L10n.Onboarding.referralResponse3
            showOptions = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.referralResponse1(userName)) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.referralResponse2) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.referralResponse3) { typed3 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showOptions = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    OnboardingReferralView(scale: 1, userName: "Riley", animate: true, onContinue: { _, _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
