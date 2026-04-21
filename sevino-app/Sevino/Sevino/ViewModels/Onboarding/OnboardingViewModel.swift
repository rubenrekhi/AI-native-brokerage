import Foundation

@Observable
final class OnboardingViewModel {
    static let totalSteps = 18

    private let onboarding: any OnboardingServiceProtocol

    // MARK: - Navigation

    private(set) var currentStep: Int
    private(set) var isComplete = false

    // MARK: - Loading / Error

    private(set) var isLoading = false
    private(set) var error: String?

    // MARK: - Form data

    private(set) var userName: String
    private(set) var referralSource: String
    private(set) var referralExtra: String?
    private(set) var mindsetSelections: Set<String>
    private(set) var goalSelections: Set<String>
    private(set) var dobString: String
    private(set) var incomeSelection: String
    private(set) var netWorthSelection: String
    private(set) var liquidCashSelection: String
    private(set) var incomeStabilitySelection: String
    private(set) var timeHorizonSelection: String
    private(set) var riskToleranceSelection: String
    private(set) var drawdownSelection: String
    private(set) var experienceSelection: String

    // MARK: - Computed

    var yearsFromDOB: Int {
        let parts = dobString.split(separator: "-")
        guard parts.count == 3, let year = Int(parts[2]) else { return 40 }
        let currentYear = Calendar.current.component(.year, from: Date.now)
        return max(65 - (currentYear - year), 1)
    }

    var referralSummary: String {
        referralExtra.map { "\(referralSource): \($0)" } ?? referralSource
    }

    // MARK: - Init

    init(
        initialStep: Int = 1,
        resumeData: OnboardingResumeManager.OnboardingResumeData? = nil,
        service: any OnboardingServiceProtocol = OnboardingService.shared
    ) {
        self.onboarding = service

        let data = resumeData ?? OnboardingResumeManager.OnboardingResumeData()
        self.currentStep = initialStep
        self.userName = data.userName
        self.referralSource = data.referralSource
        self.referralExtra = data.referralExtra
        self.mindsetSelections = data.mindsetSelections
        self.goalSelections = data.goalSelections
        self.dobString = data.dobString
        self.incomeSelection = data.incomeSelection
        self.netWorthSelection = data.netWorthSelection
        self.liquidCashSelection = data.liquidCashSelection
        self.incomeStabilitySelection = data.incomeStabilitySelection
        self.timeHorizonSelection = data.timeHorizonSelection
        self.riskToleranceSelection = data.riskToleranceSelection
        self.drawdownSelection = data.drawdownSelection
        self.experienceSelection = data.experienceSelection
    }

    // MARK: - Navigation

    func advance() {
        if currentStep < Self.totalSteps {
            currentStep += 1
        } else {
            isComplete = true
        }
    }

    func goBack() {
        if currentStep > 1 {
            currentStep -= 1
        }
    }

    // MARK: - Single-select step mapping

    enum SingleSelectStep: String {
        case annualIncome = "annual_income"
        case netWorth = "net_worth"
        case liquidNetWorth = "liquid_net_worth"
        case incomeStability = "income_stability"
        case timeHorizon = "time_horizon"
        case riskScenario = "risk_scenario"
        case maxLossTolerance = "max_loss_tolerance"
        case experience
    }

    // MARK: - Save + advance

    /// Saves the step data to the backend, then advances.
    /// On failure, records the error but still advances so the user isn't blocked
    /// — data can be re-sent on resume. Error surfacing in the UI is handled by ticket SEV-237.
    func saveAndAdvance(_ request: OnboardingPatchRequest) async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            try await onboarding.saveStep(request)
        } catch let caughtError {
            self.error = caughtError.localizedDescription
        }
        advance()
    }

    // MARK: - Step handlers

    func submitWelcome() {
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "welcome")) }
    }

    func submitName(_ name: String) {
        userName = name
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "preferred_name", preferredName: name)) }
    }

    func submitReferral(source: String, extra: String?) {
        referralSource = source
        referralExtra = extra
        let attribution = OnboardingDataMapper.buildAttribution(source: source, extra: extra)
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "attribution", attributionSource: attribution)) }
    }

    func submitMindset(_ selections: Set<String>) {
        mindsetSelections = selections
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "financial_worries", financialWorries: Array(selections))) }
    }

    func submitGoals(_ selections: Set<String>) {
        goalSelections = selections
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "investment_goals", investmentGoals: Array(selections))) }
    }

    func submitDateOfBirth(_ dob: String) {
        dobString = dob
        let isoDate = OnboardingDataMapper.formatDateOfBirth(dob)
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "date_of_birth", dateOfBirth: isoDate)) }
    }

    func submitSingleSelect(step: SingleSelectStep, value: String) {
        switch step {
        case .annualIncome: incomeSelection = value
        case .netWorth: netWorthSelection = value
        case .liquidNetWorth: liquidCashSelection = value
        case .incomeStability: incomeStabilitySelection = value
        case .timeHorizon: timeHorizonSelection = value
        case .riskScenario: riskToleranceSelection = value
        case .maxLossTolerance: drawdownSelection = value
        case .experience: experienceSelection = value
        }
        Task { await saveAndAdvance(buildSingleSelectRequest(step: step, value: value)) }
    }

    func submitRiskDisclosure() {
        let now = OnboardingDataMapper.isoTimestamp()
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "risk_disclosure", riskDisclosureAcknowledgedAt: now)) }
    }

    // MARK: - Helpers

    private func buildSingleSelectRequest(step: SingleSelectStep, value: String) -> OnboardingPatchRequest {
        var request = OnboardingPatchRequest(step: step.rawValue)
        switch step {
        case .annualIncome: request.annualIncome = value
        case .netWorth: request.netWorth = value
        case .liquidNetWorth: request.liquidNetWorth = value
        case .incomeStability: request.incomeStability = value
        case .timeHorizon: request.timeHorizon = value
        case .riskScenario: request.riskScenarioResponse = value
        case .maxLossTolerance: request.maxLossTolerance = value
        case .experience: request.experienceLevel = value
        }
        return request
    }
}
