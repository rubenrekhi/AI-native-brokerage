import Foundation

@Observable
final class AlpacaSetupViewModel {
    static let totalSteps = 10

    private let onboarding: any OnboardingServiceProtocol

    // MARK: - Navigation

    private(set) var currentStep: Int
    private(set) var isComplete = false

    // MARK: - Loading / Error

    private(set) var isLoading = false
    private(set) var error: String?

    /// The last request that failed to save — retained so the user can retry.
    /// Nil when there is no pending save-step failure (final KYC submit errors are
    /// surfaced separately via `AlpacaSetupCompleteView`).
    private(set) var pendingRetryRequest: OnboardingPatchRequest?

    // MARK: - Form data

    let userName: String
    private(set) var legalName: String
    private(set) var ssnDigits: String = ""
    private(set) var maskedSSN: String = ""
    private(set) var address: String
    private(set) var streetAddress: String
    private(set) var city: String
    private(set) var state: String
    private(set) var postalCode: String
    private(set) var citizenshipSelection: String
    private(set) var employmentStatus: String
    private(set) var employerName: String
    private(set) var jobTitle: String
    private(set) var fundingSources: Set<String>

    /// Returns a `ParsedAddress` reconstructed from saved parts when all four
    /// structured fields are present, otherwise nil. Used by the Address screen
    /// to open in its "already-selected" state on resume.
    var initialParsedAddress: ParsedAddress? {
        guard !streetAddress.isEmpty, !city.isEmpty, !state.isEmpty, !postalCode.isEmpty else {
            return nil
        }
        return ParsedAddress(
            streetAddress: streetAddress,
            city: city,
            state: state,
            postalCode: postalCode,
            fullDisplay: address
        )
    }

    init(
        userName: String,
        initialStep: Int = 1,
        resumeData: OnboardingResumeManager.AlpacaResumeData? = nil,
        service: any OnboardingServiceProtocol = OnboardingService.shared
    ) {
        self.onboarding = service
        self.userName = userName

        let data = resumeData ?? OnboardingResumeManager.AlpacaResumeData()
        self.currentStep = initialStep
        self.legalName = data.legalName
        self.address = data.address
        self.streetAddress = data.streetAddress
        self.city = data.city
        self.state = data.state
        self.postalCode = data.postalCode
        self.citizenshipSelection = data.citizenshipSelection
        self.employmentStatus = data.employmentStatus
        self.employerName = data.employerName
        self.jobTitle = data.jobTitle
        self.fundingSources = data.fundingSources
    }

    // MARK: - Step control

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
            dismissSaveError()
        }
    }

    // MARK: - Save + advance

    /// Saves the step data to the backend, then advances on success.
    /// On failure, records the error and retains the request so the user can retry —
    /// the step does NOT advance. KYC data is sensitive, so silent drops are not acceptable.
    func saveAndAdvance(_ request: OnboardingPatchRequest) async {
        isLoading = true
        defer { isLoading = false }
        do {
            try await onboarding.saveStep(request)
        } catch let caughtError {
            self.error = caughtError.localizedDescription
            self.pendingRetryRequest = request
            return
        }
        error = nil
        pendingRetryRequest = nil
        advance()
    }

    /// Re-attempts the last failed save. No-op if there is no pending retry.
    func retryLastSave() async {
        guard let request = pendingRetryRequest else { return }
        await saveAndAdvance(request)
    }

    /// Clears the save-step error without retrying. The step does not advance, so
    /// the user remains on the same screen and can edit their input.
    func dismissSaveError() {
        error = nil
        pendingRetryRequest = nil
    }

    // MARK: - KYC submit

    /// Submits the full KYC payload to Alpaca. Rethrows so the completion view
    /// can show its failure state; `error` is recorded for tests and observers.
    func submitKYC(taxId: String) async throws {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await onboarding.submit(taxId: taxId)
            print("[AlpacaSetup] KYC submitted: \(response.accountStatus)")
        } catch let caughtError {
            self.error = caughtError.localizedDescription
            throw caughtError
        }
    }

    // MARK: - Step handlers

    func submitKYCIntro() {
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro")) }
    }

    func submitLegalName(_ name: String) {
        legalName = name
        let (first, last) = OnboardingDataMapper.splitLegalName(name)
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "legal_name", firstName: first, lastName: last)) }
    }

    func submitSSN(_ ssn: String) {
        ssnDigits = ssn
        maskedSSN = "XXX-XX-\(String(ssn.suffix(4)))"
        // SSN is NOT sent to backend — held in memory for submit
        Task { await saveAndAdvance(OnboardingPatchRequest(step: "ssn")) }
    }

    func submitAddress(_ parsed: ParsedAddress) {
        address = parsed.fullDisplay
        streetAddress = parsed.streetAddress
        city = parsed.city
        state = parsed.state
        postalCode = parsed.postalCode
        Task {
            await saveAndAdvance(OnboardingPatchRequest(
                step: "address",
                streetAddress: [parsed.streetAddress],
                city: parsed.city,
                state: parsed.state,
                postalCode: parsed.postalCode
            ))
        }
    }

    func submitCitizenship(_ value: String) {
        citizenshipSelection = value
        Task {
            await saveAndAdvance(OnboardingPatchRequest(
                step: "citizenship",
                countryOfCitizenship: "USA",
                countryOfBirth: "USA",
                countryOfTaxResidence: "USA"
            ))
        }
    }

    func submitEmployment(status: String, employer: String, title: String) {
        employmentStatus = status
        employerName = employer
        jobTitle = title
        Task {
            await saveAndAdvance(OnboardingPatchRequest(
                step: "employment",
                employmentInfo: [
                    "employment_status": OnboardingDataMapper.normalizeEmploymentStatus(status),
                    "employer_name": employer,
                    "job_title": title,
                ]
            ))
        }
    }

    func submitFundingSources(_ sources: Set<String>) {
        fundingSources = sources
        Task {
            await saveAndAdvance(OnboardingPatchRequest(
                step: "funding_sources",
                fundingSources: Array(sources).map { OnboardingDataMapper.normalizeFundingSource($0) }
            ))
        }
    }

    func submitDisclosures(seniorOfficer: Bool, affiliated: Bool, political: Bool) {
        Task {
            await saveAndAdvance(OnboardingPatchRequest(
                step: "disclosures",
                disclosures: [
                    "is_control_person": seniorOfficer,
                    "is_affiliated_exchange_or_finra": affiliated,
                    "is_politically_exposed": political,
                    "immediate_family_exposed": political,
                ]
            ))
        }
    }

    func submitAgreements(agreed: Bool) {
        let now = OnboardingDataMapper.isoTimestamp()
        Task {
            await saveAndAdvance(OnboardingPatchRequest(
                step: "agreements",
                agreementsSigned: [
                    "customer_agreement": agreed ? "true" : "false",
                    "margin_agreement": agreed ? "true" : "false",
                    "signed_at": now,
                    "ip_address": "0.0.0.0",
                ]
            ))
        }
    }
}
