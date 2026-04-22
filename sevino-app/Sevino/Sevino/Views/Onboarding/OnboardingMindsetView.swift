import SwiftUI

struct OnboardingMindsetView: View {
    let scale: CGFloat
    let userName: String
    let referralSummary: String
    let animate: Bool
    let onContinue: (Set<String>) -> Void

    @State private var selected: Set<String>

    init(scale: CGFloat, userName: String, referralSummary: String, animate: Bool, initialSelected: Set<String> = [], onContinue: @escaping (Set<String>) -> Void) {
        self.scale = scale
        self.userName = userName
        self.referralSummary = referralSummary
        self.animate = animate
        self.onContinue = onContinue
        _selected = State(initialValue: initialSelected)
    }
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var showOptions = false

    private let options: [IdentifiableOption] = [
        L10n.Onboarding.mindsetSaving,
        L10n.Onboarding.mindsetIdle,
        L10n.Onboarding.mindsetBehind,
        L10n.Onboarding.mindsetOverwhelmed,
        L10n.Onboarding.mindsetWantMore,
        L10n.Onboarding.mindsetBetterTools,
    ].asIdentifiableOptions

    private let maxSelections = 3

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
                    }

                    if showOptions {
                        optionsList
                            .transition(.opacity.combined(with: .offset(y: 16)))
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
            Text(referralSummary)
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


    private var optionsList: some View {
        VStack(spacing: 12 * scale) {
            ForEach(options) { option in
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        toggle(option.value)
                    }
                } label: {
                    Text(option.value)
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                        .padding(.horizontal, 16 * scale)
                        .modifier(SevinoGlass.tintedButton(
                            tint: selected.contains(option.value)
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


    private var continueButton: some View {
        Button { onContinue(selected) } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(
            tint: selected.isEmpty ? Color.onboardingButtonInactive : Color.onboardingButtonActive
        ))
        .disabled(selected.isEmpty)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }


    private func toggle(_ option: String) {
        if selected.contains(option) {
            selected.remove(option)
        } else if selected.count < maxSelections {
            selected.insert(option)
        }
    }


    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.mindsetResponse1(userName)
            typed2 = L10n.Onboarding.mindsetResponse2
            showOptions = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.mindsetResponse1(userName)) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.mindsetResponse2) { typed2 = $0 }
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
    OnboardingMindsetView(
        scale: 1,
        userName: "Riley",
        referralSummary: "Friend: Shivam Suri",
        animate: true,
        onContinue: { _ in }
    )
    .background(Color.black)
    .preferredColorScheme(.dark)
}
