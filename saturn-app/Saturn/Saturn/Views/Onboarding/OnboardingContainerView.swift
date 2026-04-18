import SwiftUI

struct OnboardingContainerView: View {
    static let totalSteps = 18

    let initialStep: Int
    let resumeData: OnboardingResumeManager.OnboardingResumeData?
    let onComplete: (_ userName: String) -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var currentStep: Int
    @State private var animate: Bool
    @State private var scale: CGFloat = 1
    @State private var userName: String
    @State private var referralSource: String
    @State private var referralExtra: String?
    @State private var mindsetSelections: Set<String>
    @State private var goalSelections: Set<String>
    @State private var dobString: String
    @State private var incomeSelection: String
    @State private var netWorthSelection: String
    @State private var liquidCashSelection: String
    @State private var incomeStabilitySelection: String
    @State private var timeHorizonSelection: String
    @State private var riskToleranceSelection: String
    @State private var drawdownSelection: String
    @State private var experienceSelection: String
    private let onboarding: any OnboardingServiceProtocol

    init(
        initialStep: Int = 1,
        resumeData: OnboardingResumeManager.OnboardingResumeData? = nil,
        onboardingService: any OnboardingServiceProtocol = OnboardingService.shared,
        onComplete: @escaping (_ userName: String) -> Void
    ) {
        self.initialStep = initialStep
        self.resumeData = resumeData
        self.onComplete = onComplete
        self.onboarding = onboardingService

        let data = resumeData ?? OnboardingResumeManager.OnboardingResumeData()
        let isResuming = resumeData != nil && initialStep > 1

        _currentStep = State(initialValue: initialStep)
        _animate = State(initialValue: !isResuming)
        _userName = State(initialValue: data.userName)
        _referralSource = State(initialValue: data.referralSource)
        _referralExtra = State(initialValue: data.referralExtra)
        _mindsetSelections = State(initialValue: data.mindsetSelections)
        _goalSelections = State(initialValue: data.goalSelections)
        _dobString = State(initialValue: data.dobString)
        _incomeSelection = State(initialValue: data.incomeSelection)
        _netWorthSelection = State(initialValue: data.netWorthSelection)
        _liquidCashSelection = State(initialValue: data.liquidCashSelection)
        _incomeStabilitySelection = State(initialValue: data.incomeStabilitySelection)
        _timeHorizonSelection = State(initialValue: data.timeHorizonSelection)
        _riskToleranceSelection = State(initialValue: data.riskToleranceSelection)
        _drawdownSelection = State(initialValue: data.drawdownSelection)
        _experienceSelection = State(initialValue: data.experienceSelection)
    }

    var body: some View {
        VStack(spacing: 0) {
            ProgressBar(
                currentStep: currentStep,
                totalSteps: Self.totalSteps,
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
    }


    @ViewBuilder
    private var backgroundView: some View {
        if [1, 5, 7, 17].contains(currentStep) {
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

    private var yearsFromDOB: Int {
        let parts = dobString.split(separator: "-")
        guard parts.count == 3, let year = Int(parts[2]) else { return 40 }
        let currentYear = Calendar.current.component(.year, from: Date.now)
        return max(65 - (currentYear - year), 1)
    }


    @ViewBuilder
    private var stepContent: some View {
        switch currentStep {
        case 1:
            OnboardingIntroView(scale: scale, animate: animate) {
                saveAndAdvance(OnboardingPatchRequest(step: "welcome"))
            }
        case 2:
            OnboardingNameView(scale: scale, animate: animate, initialName: userName) { name in
                userName = name
                saveAndAdvance(OnboardingPatchRequest(step: "preferred_name", preferredName: name))
            }
        case 3:
            OnboardingReferralView(scale: scale, userName: userName, animate: animate) { source, extra in
                referralSource = source
                referralExtra = extra
                let attribution = OnboardingDataMapper.buildAttribution(source: source, extra: extra)
                saveAndAdvance(OnboardingPatchRequest(step: "attribution", attributionSource: attribution))
            }
        case 4:
            OnboardingMindsetView(
                scale: scale,
                userName: userName,
                referralSummary: referralExtra.map { "\(referralSource): \($0)" } ?? referralSource,
                animate: animate,
                initialSelected: mindsetSelections
            ) { selections in
                mindsetSelections = selections
                saveAndAdvance(OnboardingPatchRequest(step: "financial_worries", financialWorries: Array(selections)))
            }
        case 5:
            OnboardingReflectionView(
                scale: scale,
                userName: userName,
                worries: mindsetSelections,
                animate: animate,
                onContinue: advance
            )
        case 6:
            OnboardingGoalsView(
                scale: scale,
                userPromptText: mindsetSelections.first ?? "",
                animate: animate,
                initialSelected: goalSelections
            ) { selections in
                goalSelections = selections
                saveAndAdvance(OnboardingPatchRequest(step: "investment_goals", investmentGoals: Array(selections)))
            }
        case 7:
            OnboardingGoalsReflectionView(
                scale: scale,
                userName: userName,
                goals: goalSelections,
                animate: animate,
                onContinue: advance
            )
        case 8:
            OnboardingDOBView(
                scale: scale,
                userPromptText: goalSelections.first ?? "",
                animate: animate,
                initialDOB: dobString
            ) { dob in
                dobString = dob
                let isoDate = OnboardingDataMapper.formatDateOfBirth(dob)
                saveAndAdvance(OnboardingPatchRequest(step: "date_of_birth", dateOfBirth: isoDate))
            }
        case 9:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: dobString,
                response1: L10n.Onboarding.incomeResponse1,
                response2: L10n.Onboarding.incomeResponse2,
                options: [L10n.Onboarding.incomeUnder25k, L10n.Onboarding.income25k50k, L10n.Onboarding.income50k100k, L10n.Onboarding.income100k200k, L10n.Onboarding.income200k500k, L10n.Onboarding.income500kPlus],
                animate: animate,
                initialSelected: incomeSelection.isEmpty ? nil : incomeSelection
            ) { value in
                incomeSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "annual_income", annualIncome: value))
            }
        case 10:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: incomeSelection,
                response1: L10n.Onboarding.netWorthResponse1,
                response2: L10n.Onboarding.netWorthResponse2,
                options: [L10n.Onboarding.netWorthUnder10k, L10n.Onboarding.netWorth10k50k, L10n.Onboarding.netWorth50k100k, L10n.Onboarding.netWorth100k250k, L10n.Onboarding.netWorth250k500k, L10n.Onboarding.netWorth500k1m, L10n.Onboarding.netWorth1mPlus],
                animate: animate,
                initialSelected: netWorthSelection.isEmpty ? nil : netWorthSelection
            ) { value in
                netWorthSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "net_worth", netWorth: value))
            }
        case 11:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: netWorthSelection,
                response1: L10n.Onboarding.liquidCashResponse1,
                response2: L10n.Onboarding.liquidCashResponse2,
                options: [L10n.Onboarding.liquidUnder10k, L10n.Onboarding.liquid10k25k, L10n.Onboarding.liquid25k50k, L10n.Onboarding.liquid50k100k, L10n.Onboarding.liquid100k250k, L10n.Onboarding.liquid250kPlus],
                animate: animate,
                initialSelected: liquidCashSelection.isEmpty ? nil : liquidCashSelection
            ) { value in
                liquidCashSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "liquid_net_worth", liquidNetWorth: value))
            }
        case 12:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: liquidCashSelection,
                response1: L10n.Onboarding.incomeStabilityResponse1,
                response2: "",
                options: [
                    L10n.Onboarding.stabilityUnpredictable,
                    L10n.Onboarding.stabilityMostlyStable,
                    L10n.Onboarding.stabilitySolid,
                    L10n.Onboarding.stabilityVerySecure,
                ],
                animate: animate,
                initialSelected: incomeStabilitySelection.isEmpty ? nil : incomeStabilitySelection
            ) { value in
                incomeStabilitySelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "income_stability", incomeStability: value))
            }
        case 13:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: incomeStabilitySelection,
                response1: L10n.Onboarding.timeHorizonResponse1,
                response2: L10n.Onboarding.timeHorizonResponse2,
                options: [L10n.Onboarding.horizonUnder2, L10n.Onboarding.horizon2_5, L10n.Onboarding.horizon5_10, L10n.Onboarding.horizon10_20, L10n.Onboarding.horizon20Plus],
                animate: animate,
                initialSelected: timeHorizonSelection.isEmpty ? nil : timeHorizonSelection
            ) { value in
                timeHorizonSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "time_horizon", timeHorizon: value))
            }
        case 14:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: timeHorizonSelection,
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
                initialSelected: riskToleranceSelection.isEmpty ? nil : riskToleranceSelection
            ) { value in
                riskToleranceSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "risk_scenario", riskScenarioResponse: value))
            }
        case 15:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: riskToleranceSelection,
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
                initialSelected: drawdownSelection.isEmpty ? nil : drawdownSelection
            ) { value in
                drawdownSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "max_loss_tolerance", maxLossTolerance: value))
            }
        case 16:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: drawdownSelection,
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
                initialSelected: experienceSelection.isEmpty ? nil : experienceSelection
            ) { value in
                experienceSelection = value
                saveAndAdvance(OnboardingPatchRequest(step: "experience", experienceLevel: value))
            }
        case 17:
            OnboardingCompoundView(
                scale: scale,
                years: yearsFromDOB,
                animate: animate,
                onContinue: advance
            )
        case 18:
            OnboardingDisclaimerView(
                scale: scale,
                userPromptText: experienceSelection,
                animate: animate
            ) {
                let now = OnboardingDataMapper.isoTimestamp()
                saveAndAdvance(OnboardingPatchRequest(step: "risk_disclosure", riskDisclosureAcknowledgedAt: now))
            }
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
            completeOnboarding()
        }
    }

    /// Save the step data to the backend, then advance. If the save fails, advance anyway
    /// so the user isn't blocked — data can be re-sent on resume.
    private func saveAndAdvance(_ request: OnboardingPatchRequest) {
        Task {
            do {
                try await onboarding.saveStep(request)
            } catch {
                print("[Onboarding] Failed to save step \(request.step): \(error)")
            }
            advance()
        }
    }

    private func completeOnboarding() {
        onComplete(userName)
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
        .accessibilityValue("\(currentStep) of \(totalSteps)")
    }
}

#Preview {
    OnboardingContainerView { _ in }
}
