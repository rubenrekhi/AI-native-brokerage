import SwiftUI

struct OnboardingGoalsReflectionView: View {
    let scale: CGFloat
    let userName: String
    let goals: Set<String>
    let animate: Bool
    let onContinue: () -> Void

    @State private var typedHeading = ""
    @State private var typedBody1 = ""
    @State private var typedBody2 = ""
    @State private var typedStat = ""
    @State private var typedTagline = ""
    @State private var showSource = false
    @State private var showButton = false

    private var content: GoalsReflectionContent {
        GoalsReflectionContent.select(for: goals, name: userName)
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16 * scale) {
                    if !typedHeading.isEmpty {
                        Text(typedHeading)
                            .font(.system(size: 22 * scale, weight: .light))
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

                    if !typedStat.isEmpty {
                        Text(typedStat)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.welcomeTextSecondary)
                    }

                    if !typedTagline.isEmpty {
                        Text(typedTagline)
                            .font(.system(size: 22 * scale, weight: .light))
                            .foregroundStyle(Color.welcomeText)
                            .padding(.top, 8 * scale)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20 * scale)
                .padding(.top, 16 * scale)
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)

            if showSource {
                Text(content.source)
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.horizontal, 20 * scale)
                    .padding(.bottom, 8 * scale)
                    .transition(.opacity)
            }

            if showButton {
                Button(action: onContinue) {
                    Text(L10n.Onboarding.referralContinue)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeText)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                }
                .buttonStyle(.plain)
                .modifier(SevinoGlass.tintedButton(tint: Color.onboardingButtonActive))
                .padding(.horizontal, 32 * scale)
                .padding(.bottom, 16 * scale)
                .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showSource)
        .animation(.easeOut(duration: 0.3), value: showButton)
        .task { await animateIn() }
    }


    private func animateIn() async {
        guard animate else {
            typedHeading = content.heading
            typedBody1 = content.body1
            typedBody2 = content.body2
            typedStat = content.stat
            typedTagline = content.tagline
            showSource = true
            showButton = true
            return
        }
        try? await Task.sleep(for: .milliseconds(400))
        await typeOut(content.heading) { typedHeading = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(content.body1) { typedBody1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(content.body2) { typedBody2 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(content.stat) { typedStat = $0 }
        if !content.tagline.isEmpty {
            try? await Task.sleep(for: .milliseconds(300))
            await typeOut(content.tagline) { typedTagline = $0 }
        }
        try? await Task.sleep(for: .milliseconds(200))
        showSource = true
        try? await Task.sleep(for: .milliseconds(200))
        showButton = true
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        guard !text.isEmpty else { return }
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}


private struct GoalsReflectionContent {
    let heading: String
    let body1: String
    let body2: String
    let stat: String
    let tagline: String
    let source: String

    static func select(for goals: Set<String>, name: String) -> GoalsReflectionContent {
        if goals.contains(L10n.Onboarding.goalGrowWealth)
            || goals.contains(L10n.Onboarding.goalRetirement)
            || goals.contains(L10n.Onboarding.goalBigGoal)
        {
            return variantA()
        } else if goals.contains(L10n.Onboarding.goalSafetyNet)
            || goals.contains(L10n.Onboarding.goalCashHarder)
        {
            return variantB(name: name)
        } else {
            return variantC()
        }
    }

    private static func variantA() -> GoalsReflectionContent {
        GoalsReflectionContent(
            heading: L10n.Onboarding.goalsReflectionAHeading,
            body1: L10n.Onboarding.goalsReflectionABody1,
            body2: L10n.Onboarding.goalsReflectionABody2,
            stat: L10n.Onboarding.goalsReflectionAStat,
            tagline: L10n.Onboarding.goalsReflectionATagline,
            source: L10n.Onboarding.goalsReflectionASource
        )
    }

    private static func variantB(name: String) -> GoalsReflectionContent {
        GoalsReflectionContent(
            heading: L10n.Onboarding.goalsReflectionBHeading(name),
            body1: L10n.Onboarding.goalsReflectionBBody1,
            body2: L10n.Onboarding.goalsReflectionBBody2,
            stat: L10n.Onboarding.goalsReflectionBStat,
            tagline: "",
            source: L10n.Onboarding.goalsReflectionBSource
        )
    }

    private static func variantC() -> GoalsReflectionContent {
        GoalsReflectionContent(
            heading: L10n.Onboarding.goalsReflectionCHeading,
            body1: L10n.Onboarding.goalsReflectionCBody1,
            body2: L10n.Onboarding.goalsReflectionCBody2,
            stat: L10n.Onboarding.goalsReflectionCStat,
            tagline: L10n.Onboarding.goalsReflectionCTagline,
            source: L10n.Onboarding.goalsReflectionCSource
        )
    }
}

#Preview {
    OnboardingGoalsReflectionView(
        scale: 1,
        userName: "Riley",
        goals: ["Grow my wealth over time"],
        animate: true,
        onContinue: {}
    )
    .background(Color.black)
    .preferredColorScheme(.dark)
}
