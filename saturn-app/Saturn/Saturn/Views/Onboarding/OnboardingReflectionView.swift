import SwiftUI

struct OnboardingReflectionView: View {
    let scale: CGFloat
    let userName: String
    let worries: Set<String>
    let animate: Bool
    let onContinue: () -> Void

    @State private var typedHeading = ""
    @State private var typedBody1 = ""
    @State private var typedBody2 = ""
    @State private var typedStat = ""
    @State private var typedStatDesc = ""
    @State private var showSource = false
    @State private var showButton = false

    private var content: ReflectionContent {
        ReflectionContent.select(for: worries, name: userName)
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
                            .font(.system(size: 48 * scale, weight: .thin))
                            .foregroundStyle(Color.welcomeText)
                            .padding(.top, 8 * scale)
                    }

                    if !typedStatDesc.isEmpty {
                        Text(typedStatDesc)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.welcomeTextSecondary)
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
                .modifier(SaturnGlass.tintedButton(tint: Color.onboardingButtonActive))
                .padding(.horizontal, 32 * scale)
                .padding(.bottom, 16 * scale)
                .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showSource)
        .animation(.easeOut(duration: 0.3), value: showButton)
        .task { await animateIn() }
    }

    // MARK: - Animation

    private func animateIn() async {
        guard animate else {
            typedHeading = content.heading
            typedBody1 = content.body1
            typedBody2 = content.body2
            typedStat = content.statNumber
            typedStatDesc = content.statDescription
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
        try? await Task.sleep(for: .milliseconds(300))
        await typeOut(content.statNumber, speed: .milliseconds(80)) { typedStat = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(content.statDescription) { typedStatDesc = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        showSource = true
        try? await Task.sleep(for: .milliseconds(200))
        showButton = true
    }

    private func typeOut(_ text: String, speed: Duration = .milliseconds(25), update: (String) -> Void) async {
        guard !text.isEmpty else { return }
        for i in 1...text.count {
            try? await Task.sleep(for: speed)
            update(String(text.prefix(i)))
        }
    }
}

// MARK: - Variant Content

private struct ReflectionContent {
    let heading: String
    let body1: String
    let body2: String
    let statNumber: String
    let statDescription: String
    let source: String

    static func select(for worries: Set<String>, name: String) -> ReflectionContent {
        if worries.contains(L10n.Onboarding.mindsetSaving)
            || worries.contains(L10n.Onboarding.mindsetBehind)
        {
            return variantA(name: name)
        } else if worries.contains(L10n.Onboarding.mindsetIdle) {
            return variantB()
        } else if worries.contains(L10n.Onboarding.mindsetOverwhelmed)
            || worries.contains(L10n.Onboarding.mindsetWantMore)
        {
            return variantC(name: name)
        } else {
            return variantD()
        }
    }

    private static func variantA(name: String) -> ReflectionContent {
        ReflectionContent(
            heading: L10n.Onboarding.reflectionAHeading(name),
            body1: L10n.Onboarding.reflectionABody1,
            body2: L10n.Onboarding.reflectionABody2,
            statNumber: L10n.Onboarding.reflectionAStatNumber,
            statDescription: L10n.Onboarding.reflectionAStatDesc,
            source: L10n.Onboarding.reflectionASource
        )
    }

    private static func variantB() -> ReflectionContent {
        ReflectionContent(
            heading: L10n.Onboarding.reflectionBHeading,
            body1: L10n.Onboarding.reflectionBBody1,
            body2: L10n.Onboarding.reflectionBBody2,
            statNumber: L10n.Onboarding.reflectionBStatNumber,
            statDescription: L10n.Onboarding.reflectionBStatDesc,
            source: L10n.Onboarding.reflectionBSource
        )
    }

    private static func variantC(name: String) -> ReflectionContent {
        ReflectionContent(
            heading: L10n.Onboarding.reflectionCHeading(name),
            body1: L10n.Onboarding.reflectionCBody1,
            body2: L10n.Onboarding.reflectionCBody2,
            statNumber: L10n.Onboarding.reflectionCStatNumber,
            statDescription: L10n.Onboarding.reflectionCStatDesc,
            source: L10n.Onboarding.reflectionCSource
        )
    }

    private static func variantD() -> ReflectionContent {
        ReflectionContent(
            heading: L10n.Onboarding.reflectionDHeading,
            body1: L10n.Onboarding.reflectionDBody1,
            body2: L10n.Onboarding.reflectionDBody2,
            statNumber: L10n.Onboarding.reflectionDStatNumber,
            statDescription: L10n.Onboarding.reflectionDStatDesc,
            source: L10n.Onboarding.reflectionDSource
        )
    }
}

#Preview {
    OnboardingReflectionView(
        scale: 1,
        userName: "Riley",
        worries: ["Not sure I'm saving enough"],
        animate: true,
        onContinue: {}
    )
    .background(Color.black)
    .preferredColorScheme(.dark)
}
