import SwiftUI

struct OnboardingContainerView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let onComplete: (_ userName: String) -> Void

    @State private var viewModel: OnboardingViewModel
    @State private var animate: Bool
    @State private var scale: CGFloat = 1

    init(
        initialStep: Int = 1,
        resumeData: OnboardingResumeManager.OnboardingResumeData? = nil,
        onboardingService: any OnboardingServiceProtocol = OnboardingService.shared,
        onComplete: @escaping (_ userName: String) -> Void
    ) {
        self.onComplete = onComplete
        let isResuming = resumeData != nil && initialStep > 1
        _viewModel = State(initialValue: OnboardingViewModel(
            initialStep: initialStep,
            resumeData: resumeData,
            service: onboardingService
        ))
        _animate = State(initialValue: !isResuming)
    }

    var body: some View {
        VStack(spacing: 0) {
            OnboardingProgressBar(
                currentStep: viewModel.currentStep,
                totalSteps: OnboardingViewModel.totalSteps,
                scale: scale
            )
            .padding(.top, 8 * scale)
            .padding(.horizontal, 32 * scale)
            .padding(.bottom, 8 * scale)

            AuthHeaderView(scale: scale, onBack: goBack)

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
        .onChange(of: viewModel.isComplete) { _, isComplete in
            if isComplete {
                onComplete(viewModel.userName)
            }
        }
    }

    @ViewBuilder
    private var backgroundView: some View {
        if [1, 5, 7, 17].contains(viewModel.currentStep) {
            OnboardingBackgroundView()
        } else {
            LinearGradient(
                stops: [
                    .init(color: Color.sevinoAccent, location: 0),
                    .init(color: Color.sevinoPrimary, location: 0.2),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()
        }
    }

    @ViewBuilder
    private var stepContent: some View {
        switch viewModel.currentStep {
        case 1:
            OnboardingIntroView(scale: scale, animate: animate) {
                viewModel.submitWelcome()
            }
        case 2:
            OnboardingNameView(scale: scale, animate: animate, initialName: viewModel.userName) { name in
                viewModel.submitName(name)
            }
        case 3:
            OnboardingReferralView(scale: scale, userName: viewModel.userName, animate: animate) { source, extra in
                viewModel.submitReferral(source: source, extra: extra)
            }
        case 4:
            OnboardingMindsetView(
                scale: scale,
                userName: viewModel.userName,
                referralSummary: viewModel.referralSummary,
                animate: animate,
                initialSelected: viewModel.mindsetSelections
            ) { selections in
                viewModel.submitMindset(selections)
            }
        case 5:
            OnboardingReflectionView(
                scale: scale,
                userName: viewModel.userName,
                worries: viewModel.mindsetSelections,
                animate: animate,
                onContinue: advance
            )
        case 6:
            OnboardingGoalsView(
                scale: scale,
                userPromptText: viewModel.mindsetSelections.first ?? "",
                animate: animate,
                initialSelected: viewModel.goalSelections
            ) { selections in
                viewModel.submitGoals(selections)
            }
        case 7:
            OnboardingGoalsReflectionView(
                scale: scale,
                userName: viewModel.userName,
                goals: viewModel.goalSelections,
                animate: animate,
                onContinue: advance
            )
        case 8:
            OnboardingDOBView(
                scale: scale,
                userPromptText: viewModel.goalSelections.first ?? "",
                animate: animate,
                initialDOB: viewModel.dobString
            ) { dob in
                viewModel.submitDateOfBirth(dob)
            }
        case 9:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.dobString,
                response1: L10n.Onboarding.incomeResponse1,
                response2: L10n.Onboarding.incomeResponse2,
                options: [L10n.Onboarding.incomeUnder25k, L10n.Onboarding.income25k50k, L10n.Onboarding.income50k100k, L10n.Onboarding.income100k200k, L10n.Onboarding.income200k500k, L10n.Onboarding.income500kPlus],
                animate: animate,
                initialSelected: viewModel.incomeSelection.isEmpty ? nil : viewModel.incomeSelection
            ) { value in
                viewModel.submitSingleSelect(step: .annualIncome, value: value)
            }
        case 10:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.incomeSelection,
                response1: L10n.Onboarding.netWorthResponse1,
                response2: L10n.Onboarding.netWorthResponse2,
                options: [L10n.Onboarding.netWorthUnder10k, L10n.Onboarding.netWorth10k50k, L10n.Onboarding.netWorth50k100k, L10n.Onboarding.netWorth100k250k, L10n.Onboarding.netWorth250k500k, L10n.Onboarding.netWorth500k1m, L10n.Onboarding.netWorth1mPlus],
                animate: animate,
                initialSelected: viewModel.netWorthSelection.isEmpty ? nil : viewModel.netWorthSelection
            ) { value in
                viewModel.submitSingleSelect(step: .netWorth, value: value)
            }
        case 11:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.netWorthSelection,
                response1: L10n.Onboarding.liquidCashResponse1,
                response2: L10n.Onboarding.liquidCashResponse2,
                options: [L10n.Onboarding.liquidUnder10k, L10n.Onboarding.liquid10k25k, L10n.Onboarding.liquid25k50k, L10n.Onboarding.liquid50k100k, L10n.Onboarding.liquid100k250k, L10n.Onboarding.liquid250kPlus],
                animate: animate,
                initialSelected: viewModel.liquidCashSelection.isEmpty ? nil : viewModel.liquidCashSelection
            ) { value in
                viewModel.submitSingleSelect(step: .liquidNetWorth, value: value)
            }
        case 12:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.liquidCashSelection,
                response1: L10n.Onboarding.incomeStabilityResponse1,
                response2: "",
                options: [
                    L10n.Onboarding.stabilityUnpredictable,
                    L10n.Onboarding.stabilityMostlyStable,
                    L10n.Onboarding.stabilitySolid,
                    L10n.Onboarding.stabilityVerySecure,
                ],
                animate: animate,
                initialSelected: viewModel.incomeStabilitySelection.isEmpty ? nil : viewModel.incomeStabilitySelection
            ) { value in
                viewModel.submitSingleSelect(step: .incomeStability, value: value)
            }
        case 13:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.incomeStabilitySelection,
                response1: L10n.Onboarding.timeHorizonResponse1,
                response2: L10n.Onboarding.timeHorizonResponse2,
                options: [L10n.Onboarding.horizonUnder2, L10n.Onboarding.horizon2_5, L10n.Onboarding.horizon5_10, L10n.Onboarding.horizon10_20, L10n.Onboarding.horizon20Plus],
                animate: animate,
                initialSelected: viewModel.timeHorizonSelection.isEmpty ? nil : viewModel.timeHorizonSelection
            ) { value in
                viewModel.submitSingleSelect(step: .timeHorizon, value: value)
            }
        case 14:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.timeHorizonSelection,
                response1: L10n.Onboarding.riskToleranceResponse1,
                response2: L10n.Onboarding.riskToleranceResponse2,
                response3: L10n.Onboarding.riskToleranceResponse3,
                options: [
                    L10n.Onboarding.riskSellAll,
                    L10n.Onboarding.riskSellSome,
                    L10n.Onboarding.riskHold,
                    L10n.Onboarding.riskBuyMore,
                    L10n.Onboarding.riskNotSure,
                ],
                animate: animate,
                initialSelected: viewModel.riskToleranceSelection.isEmpty ? nil : viewModel.riskToleranceSelection
            ) { value in
                viewModel.submitSingleSelect(step: .riskScenario, value: value)
            }
        case 15:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.riskToleranceSelection,
                response1: L10n.Onboarding.drawdownResponse1,
                response2: "",
                options: [
                    L10n.Onboarding.drawdown0_5,
                    L10n.Onboarding.drawdown5_15,
                    L10n.Onboarding.drawdown15_25,
                    L10n.Onboarding.drawdown25_40,
                    L10n.Onboarding.drawdown40Plus,
                ],
                animate: animate,
                initialSelected: viewModel.drawdownSelection.isEmpty ? nil : viewModel.drawdownSelection
            ) { value in
                viewModel.submitSingleSelect(step: .maxLossTolerance, value: value)
            }
        case 16:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.drawdownSelection,
                response1: L10n.Onboarding.experienceResponse1,
                response2: "",
                options: [
                    L10n.Onboarding.experienceNever,
                    L10n.Onboarding.experienceLittle,
                    L10n.Onboarding.experienceRegular,
                    L10n.Onboarding.experienceActive,
                    L10n.Onboarding.experienceAdvanced,
                ],
                animate: animate,
                initialSelected: viewModel.experienceSelection.isEmpty ? nil : viewModel.experienceSelection
            ) { value in
                viewModel.submitSingleSelect(step: .experience, value: value)
            }
        case 17:
            OnboardingCompoundView(
                scale: scale,
                years: viewModel.yearsFromDOB,
                animate: animate,
                onContinue: advance
            )
        case 18:
            OnboardingDisclaimerView(
                scale: scale,
                userPromptText: viewModel.experienceSelection,
                animate: animate
            ) {
                viewModel.submitRiskDisclosure()
            }
        default:
            Spacer()
        }
    }

    // MARK: - View-level navigation (handles animation)

    private func goBack() {
        if viewModel.currentStep > 1 {
            animate = false
            withAnimation(.easeInOut(duration: 0.3)) {
                viewModel.goBack()
            }
        }
    }

    private func advance() {
        animate = !reduceMotion
        withAnimation(.easeInOut(duration: 0.3)) {
            viewModel.advance()
        }
    }
}


#Preview {
    OnboardingContainerView { _ in }
}
