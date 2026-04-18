import Foundation

/// Determines where to route the user based on their onboarding status,
/// and provides saved data to pre-populate screens.
enum OnboardingResumeManager {

    enum Destination {
        case home
        case onboarding(step: Int, data: OnboardingResumeData)
        case alpacaSetup(step: Int, data: AlpacaResumeData)
        case loading
    }

    /// All saved Phase 1 data, mapped to OnboardingContainerView's @State var names.
    struct OnboardingResumeData {
        var userName: String = ""
        var referralSource: String = ""
        var referralExtra: String? = nil
        var mindsetSelections: Set<String> = []
        var goalSelections: Set<String> = []
        var dobString: String = ""
        var incomeSelection: String = ""
        var netWorthSelection: String = ""
        var liquidCashSelection: String = ""
        var incomeStabilitySelection: String = ""
        var timeHorizonSelection: String = ""
        var riskToleranceSelection: String = ""
        var drawdownSelection: String = ""
        var experienceSelection: String = ""
    }

    /// All saved Phase 2 data, mapped to AlpacaSetupContainerView's @State var names.
    struct AlpacaResumeData {
        var userName: String = ""
        var legalName: String = ""
        var address: String = ""
        var citizenshipSelection: String = ""
        var employmentStatus: String = ""
        var employerName: String = ""
        var jobTitle: String = ""
        var fundingSources: Set<String> = []
    }

    // MARK: - Step mapping

    /// Phase 1 step strings in screen order. The index + 1 = the screen that SAVED this step.
    /// Reflection/display-only screens (5, 7, 17) are not in this list since they don't save data.
    private static let phase1Steps = [
        "welcome",            // screen 1
        "preferred_name",     // screen 2
        "attribution",        // screen 3
        "financial_worries",  // screen 4
        "investment_goals",   // screen 6
        "date_of_birth",      // screen 8
        "annual_income",      // screen 9
        "net_worth",          // screen 10
        "liquid_net_worth",   // screen 11
        "income_stability",   // screen 12
        "time_horizon",       // screen 13
        "risk_scenario",      // screen 14
        "max_loss_tolerance", // screen 15
        "experience",         // screen 16
        "risk_disclosure",    // screen 18
    ]

    /// Maps a Phase 1 step string to the OnboardingContainerView currentStep to resume at.
    /// Returns the screen AFTER the completed one.
    private static let phase1ResumeStep: [String: Int] = [
        "welcome": 2,
        "preferred_name": 3,
        "attribution": 4,
        "financial_worries": 5,   // reflection screen
        "investment_goals": 7,    // reflection screen
        "date_of_birth": 9,
        "annual_income": 10,
        "net_worth": 11,
        "liquid_net_worth": 12,
        "income_stability": 13,
        "time_horizon": 14,
        "risk_scenario": 15,
        "max_loss_tolerance": 16,
        "experience": 17,         // compound chart
        "risk_disclosure": 18,    // last Phase 1 screen — but Phase 1 done, go to Alpaca
    ]

    /// Phase 2 step strings in screen order.
    private static let phase2Steps = [
        "kyc_intro",       // screen 1
        "legal_name",      // screen 2
        "ssn",             // screen 3
        "address",         // screen 4
        "citizenship",     // screen 5
        "employment",      // screen 6
        "funding_sources", // screen 7
        "disclosures",     // screen 8
        "agreements",      // screen 9
    ]

    /// Maps a Phase 2 step string to the AlpacaSetupContainerView currentStep to resume at.
    /// Steps at or past SSN always resume at step 3 (SSN screen) since SSN is never stored.
    private static let phase2ResumeStep: [String: Int] = [
        "kyc_intro": 2,
        "legal_name": 3,
        "ssn": 3,
        "address": 3,
        "citizenship": 3,
        "employment": 3,
        "funding_sources": 3,
        "disclosures": 3,
        "agreements": 3,
    ]

    // MARK: - Public API

    static func destination(from status: OnboardingStatusResponse) -> Destination {
        if status.onboardingCompleted || status.onboardingStep == "submitted" {
            return .home
        }

        guard let step = status.onboardingStep else {
            // No step saved yet — start from the beginning
            return .onboarding(step: 1, data: OnboardingResumeData())
        }

        // Check Phase 1
        if let resumeStep = phase1ResumeStep[step] {
            if step == "risk_disclosure" {
                // Phase 1 complete — go to Alpaca setup
                return .alpacaSetup(step: 1, data: buildAlpacaResumeData(from: status))
            }
            return .onboarding(step: resumeStep, data: buildOnboardingResumeData(from: status))
        }

        // Check Phase 2
        if let resumeStep = phase2ResumeStep[step] {
            return .alpacaSetup(step: resumeStep, data: buildAlpacaResumeData(from: status))
        }

        // Unknown step — start from beginning
        return .onboarding(step: 1, data: OnboardingResumeData())
    }

    // MARK: - Data builders

    private static func buildOnboardingResumeData(from status: OnboardingStatusResponse) -> OnboardingResumeData {
        var data = OnboardingResumeData()

        if let profile = status.profile {
            data.userName = profile.preferredName ?? ""
        }

        if let fin = status.financialProfile {
            data.mindsetSelections = Set(fin.financialWorries ?? [])
            data.goalSelections = Set(fin.investmentGoals ?? [])
            data.incomeSelection = fin.annualIncome ?? ""
            data.netWorthSelection = fin.netWorth ?? ""
            data.liquidCashSelection = fin.liquidNetWorth ?? ""
            data.incomeStabilitySelection = fin.incomeStability ?? ""
            data.timeHorizonSelection = fin.timeHorizon ?? ""
            data.riskToleranceSelection = fin.riskScenarioResponse ?? ""
            data.drawdownSelection = fin.maxLossTolerance ?? ""
            data.experienceSelection = fin.experienceLevel ?? ""
        }

        if let profile = status.profile, let dob = profile.dateOfBirth {
            // Convert YYYY-MM-DD to MM-DD-YYYY for the DOB view
            let parts = dob.split(separator: "-")
            if parts.count == 3 {
                data.dobString = "\(parts[1])-\(parts[2])-\(parts[0])"
            }
        }

        // Attribution is stored as a combined string, we can't reliably split it back
        // Just store as referralSource
        if let profile = status.profile {
            data.referralSource = profile.attributionSource ?? ""
        }

        return data
    }

    private static func buildAlpacaResumeData(from status: OnboardingStatusResponse) -> AlpacaResumeData {
        var data = AlpacaResumeData()

        if let profile = status.profile {
            data.userName = profile.preferredName ?? ""
            let first = profile.firstName ?? ""
            let last = profile.lastName ?? ""
            data.legalName = last.isEmpty ? first : "\(first) \(last)"

            // Reconstruct display address
            let parts = [
                profile.streetAddress?.first,
                profile.city,
                profile.state,
                profile.postalCode
            ].compactMap { $0 }.filter { !$0.isEmpty }
            data.address = parts.joined(separator: ", ")
        }

        if let fin = status.financialProfile {
            let empInfo = fin.employmentInfo
            data.employmentStatus = empInfo?["employment_status"] ?? ""
            data.employerName = empInfo?["employer_name"] ?? ""
            data.jobTitle = empInfo?["job_title"] ?? ""
            data.fundingSources = Set(fin.fundingSources ?? [])
        }

        return data
    }
}
