import Foundation

// MARK: - Request Models

/// Flexible request for PATCH /v1/onboarding — all fields optional except step.
/// Only include fields relevant to the current screen.
struct OnboardingPatchRequest: Encodable {
    let step: String

    // Phase 1 — user profile
    var preferredName: String?
    var dateOfBirth: String?
    var phoneNumber: String?
    var attributionSource: String?
    var riskDisclosureAcknowledgedAt: String?

    // Phase 1 — financial profile
    var financialWorries: [String]?
    var investmentGoals: [String]?
    var annualIncome: String?
    var netWorth: String?
    var liquidNetWorth: String?
    var incomeStability: String?
    var timeHorizon: String?
    var riskScenarioResponse: String?
    var maxLossTolerance: String?
    var experienceLevel: String?

    // Phase 2 — KYC profile
    var firstName: String?
    var middleName: String?
    var lastName: String?
    var streetAddress: [String]?
    var city: String?
    var state: String?
    var postalCode: String?
    var countryOfCitizenship: String?
    var countryOfBirth: String?
    var countryOfTaxResidence: String?

    // Phase 2 — financial
    var employmentInfo: [String: String]?
    var fundingSources: [String]?

    // Phase 2 — compliance
    var disclosures: [String: Bool]?
    var agreementsSigned: [String: String]?
}

/// Request for POST /v1/onboarding/submit — SSN forwarded to Alpaca, never stored.
struct OnboardingSubmitRequest: Encodable {
    let taxId: String
    let taxIdType: String

    init(taxId: String, taxIdType: String = "USA_SSN") {
        self.taxId = taxId
        self.taxIdType = taxIdType
    }
}

// MARK: - Response Models

/// Response from PATCH /v1/onboarding
struct OnboardingPatchResponse: Decodable {
    let step: String
}

/// Response from POST /v1/onboarding/submit
struct OnboardingSubmitResponse: Decodable {
    let accountStatus: String
    let alpacaAccountId: String
}

/// Response from GET /v1/onboarding/status
struct OnboardingStatusResponse: Decodable {
    let onboardingCompleted: Bool
    let onboardingStep: String?
    let accountStatus: String?
    let profile: ProfileData?
    let financialProfile: FinancialProfileData?
}

struct ProfileData: Decodable {
    let preferredName: String?
    let firstName: String?
    let middleName: String?
    let lastName: String?
    let dateOfBirth: String?
    let email: String?
    let phoneNumber: String?
    let streetAddress: [String]?
    let city: String?
    let state: String?
    let postalCode: String?
    let countryOfCitizenship: String?
    let countryOfBirth: String?
    let countryOfTaxResidence: String?
}

struct FinancialProfileData: Decodable {
    let financialWorries: [String]?
    let investmentGoals: [String]?
    let annualIncome: String?
    let netWorth: String?
    let liquidNetWorth: String?
    let incomeStability: String?
    let timeHorizon: String?
    let riskScenarioResponse: String?
    let maxLossTolerance: String?
    let experienceLevel: String?
    let fundingSources: [String]?
}
