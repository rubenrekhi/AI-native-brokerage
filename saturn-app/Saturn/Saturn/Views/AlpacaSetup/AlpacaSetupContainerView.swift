import SwiftUI

struct AlpacaSetupContainerView: View {
    static let totalSteps = 10 // steps 1-9 are form, step 10 is completion

    let userName: String
    let onComplete: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var currentStep = 1
    @State private var animate = true
    @State private var scale: CGFloat = 1
    @State private var legalName = ""
    @State private var maskedSSN = ""
    @State private var address = ""
    @State private var citizenshipSelection = ""
    @State private var fundingSourceSummary = ""

    var body: some View {
        VStack(spacing: 0) {
            if currentStep > 1 {
                ProgressBar(
                    currentStep: currentStep - 1,
                    totalSteps: Self.totalSteps - 1,
                    scale: scale
                )
                .padding(.top, 8 * scale)
                .padding(.horizontal, 32 * scale)
                .padding(.bottom, 8 * scale)

                if currentStep == 10 {
                    Image("logo_white")
                        .resizable()
                        .scaledToFit()
                        .frame(height: 36 * scale)
                        .accessibilityLabel(L10n.General.appName)
                        .padding(.top, 8 * scale)
                } else {
                    AuthHeaderView(scale: scale, onBack: goBack)
                }
            }

            stepContent
        }
        .background { backgroundView }
        .preferredColorScheme(.dark)
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    scale = geo.size.width / 393
                }
            }
        }
    }


    @ViewBuilder
    private var backgroundView: some View {
        if currentStep == 1 || currentStep == 10 {
            OnboardingBackgroundView()
        } else {
            LinearGradient(
                stops: [
                    .init(color: Color.saturnAccent, location: 0),
                    .init(color: Color.saturnPrimary, location: 0.2),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()
        }
    }


    @ViewBuilder
    private var stepContent: some View {
        switch currentStep {
        case 1:
            AlpacaSetupIntroView(scale: scale, userName: userName, animate: animate, onContinue: advance)
        case 2:
            AlpacaLegalNameView(scale: scale, animate: animate) { name in
                legalName = name
                advance()
            }
        case 3:
            AlpacaSSNView(scale: scale, userPromptText: legalName, animate: animate) { ssn in
                maskedSSN = "XXX-XX-\(String(ssn.suffix(4)))"
                advance()
            }
        case 4:
            AlpacaAddressView(scale: scale, userPromptText: maskedSSN, animate: animate) { value in
                address = value
                advance()
            }
        case 5:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: address,
                response1: L10n.Onboarding.alpacaCitizenshipResponse1,
                response2: "",
                options: [
                    L10n.Onboarding.alpacaCitizenYes,
                    L10n.Onboarding.alpacaCitizenResident,
                    L10n.Onboarding.alpacaCitizenNo,
                ],
                animate: animate
            ) { value in
                citizenshipSelection = value
                advance()
            }
        case 6:
            AlpacaEmploymentView(
                scale: scale,
                userPromptText: citizenshipSelection,
                animate: animate,
                onContinue: { fundingSourceSummary = L10n.Onboarding.alpacaStatusEmployed; advance() }
            )
        case 7:
            AlpacaFundingSourceView(
                scale: scale,
                userPromptText: fundingSourceSummary,
                animate: animate,
                onContinue: advance
            )
        case 8:
            AlpacaRegulatoryView(
                scale: scale,
                userPromptText: L10n.Onboarding.alpacaFundingSavings,
                animate: animate,
                onContinue: advance
            )
        case 9:
            AlpacaAgreementsView(
                scale: scale,
                animate: animate,
                onContinue: advance
            )
        case 10:
            AlpacaSetupCompleteView(
                scale: scale,
                userName: userName,
                onContinue: onComplete
            )
        default:
            Spacer()
        }
    }

    private func goBack() {
        if currentStep > 1 {
            animate = false
            withAnimation(.easeInOut(duration: 0.3)) {
                currentStep -= 1
            }
        }
    }

    private func advance() {
        if currentStep < Self.totalSteps {
            animate = !reduceMotion
            withAnimation(.easeInOut(duration: 0.3)) {
                currentStep += 1
            }
        } else {
            onComplete()
        }
    }
}


private struct ProgressBar: View {
    let currentStep: Int
    let totalSteps: Int
    let scale: CGFloat

    private var progress: CGFloat {
        CGFloat(currentStep) / CGFloat(totalSteps)
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.onboardingProgressTrack)

                Capsule()
                    .fill(Color.onboardingProgressFill)
                    .frame(width: max(geo.size.width * progress, geo.size.height))
                    .animation(.easeInOut(duration: 0.3), value: currentStep)
            }
        }
        .frame(height: 4 * scale)
    }
}

#Preview {
    AlpacaSetupContainerView(userName: "Riley", onComplete: {})
}
