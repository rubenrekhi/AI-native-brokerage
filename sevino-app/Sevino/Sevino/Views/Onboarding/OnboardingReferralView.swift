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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let sources: [IdentifiableOption] = [
        L10n.Onboarding.referralTiktok, L10n.Onboarding.referralInstagram,
        L10n.Onboarding.referralTwitter, L10n.Onboarding.referralFriend,
        L10n.Onboarding.referralGoogle, L10n.Onboarding.referralReddit,
        L10n.Onboarding.referralAiTool, L10n.Onboarding.referralLinkedin,
        L10n.Onboarding.referralArticle, L10n.Onboarding.referralOther,
    ].asIdentifiableOptions

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


    private var userPrompt: some View {
        HStack {
            Spacer()
            Text(userName)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 10 * scale)
                .background(
                    Color.sevinoGreyAccent.opacity(0.4),
                    in: RoundedRectangle(cornerRadius: 16 * scale)
                )
        }
    }


    private var optionsGrid: some View {
        LazyVGrid(
            columns: [
                GridItem(.flexible(), spacing: 12 * scale),
                GridItem(.flexible(), spacing: 12 * scale),
            ],
            spacing: 12 * scale
        ) {
            ForEach(sources) { source in
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        selectedSource = source.value
                    }
                    if !needsExtraText { extraText = "" }
                } label: {
                    Text(source.value)
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                        .padding(.horizontal, 16 * scale)
                        .modifier(SevinoGlass.tintedButton(
                            tint: selectedSource == source.value
                                ? Color.sevinoAccent
                                : Color.clear,
                            cornerRadius: 16
                        ))
                        .contentShape(.rect(cornerRadius: 16))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.top, 8 * scale)
    }


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
        .modifier(SevinoGlass.nav)
    }


    private var continueButton: some View {
        Button { onContinue(selectedSource ?? "", extraText.isEmpty ? nil : extraText) } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(
            tint: selectedSource != nil ? Color.onboardingButtonActive : Color.onboardingButtonInactive
        ))
        .disabled(selectedSource == nil)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }


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
        await TypewriterAnimation.typeOut(L10n.Onboarding.referralResponse1(userName), reduceMotion: reduceMotion) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await TypewriterAnimation.typeOut(L10n.Onboarding.referralResponse2, reduceMotion: reduceMotion) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await TypewriterAnimation.typeOut(L10n.Onboarding.referralResponse3, reduceMotion: reduceMotion) { typed3 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showOptions = true }
    }
}

#Preview {
    OnboardingReferralView(scale: 1, userName: "Riley", animate: true, onContinue: { _, _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
