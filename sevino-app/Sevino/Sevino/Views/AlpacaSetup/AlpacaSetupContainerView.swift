import SwiftUI

struct AlpacaSetupContainerView: View {
    static let totalSteps = 10 // steps 1-9 are form, step 10 is completion

    let userName: String
    let initialStep: Int
    let resumeData: OnboardingResumeManager.AlpacaResumeData?
    let onComplete: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var currentStep: Int
    @State private var animate: Bool
    @State private var scale: CGFloat = 1
    @State private var legalName: String
    @State private var ssnDigits: String = ""
    @State private var maskedSSN: String = ""
    @State private var address: String
    @State private var citizenshipSelection: String
    @State private var employmentStatus: String
    @State private var employerName: String
    @State private var jobTitle: String
    @State private var fundingSources: Set<String>
    private let onboarding: any OnboardingServiceProtocol

    init(
        userName: String,
        initialStep: Int = 1,
        resumeData: OnboardingResumeManager.AlpacaResumeData? = nil,
        onboardingService: any OnboardingServiceProtocol = OnboardingService.shared,
        onComplete: @escaping () -> Void
    ) {
        self.userName = userName
        self.initialStep = initialStep
        self.resumeData = resumeData
        self.onComplete = onComplete
        self.onboarding = onboardingService

        let data = resumeData ?? OnboardingResumeManager.AlpacaResumeData()
        let isResuming = resumeData != nil && initialStep > 1

        _currentStep = State(initialValue: initialStep)
        _animate = State(initialValue: !isResuming)
        _legalName = State(initialValue: data.legalName)
        _address = State(initialValue: data.address)
        _citizenshipSelection = State(initialValue: data.citizenshipSelection)
        _employmentStatus = State(initialValue: data.employmentStatus)
        _employerName = State(initialValue: data.employerName)
        _jobTitle = State(initialValue: data.jobTitle)
        _fundingSources = State(initialValue: data.fundingSources)
    }

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
            AlpacaSetupIntroView(scale: scale, userName: userName, animate: animate) {
                saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))
            }
        case 2:
            AlpacaLegalNameView(scale: scale, animate: animate, initialName: legalName) { name in
                legalName = name
                let (first, last) = OnboardingDataMapper.splitLegalName(name)
                saveAndAdvance(OnboardingPatchRequest(step: "legal_name", firstName: first, lastName: last))
            }
        case 3:
            AlpacaSSNView(scale: scale, userPromptText: legalName, animate: animate) { ssn in
                ssnDigits = ssn
                maskedSSN = "XXX-XX-\(String(ssn.suffix(4)))"
                // SSN is NOT sent to backend — held in memory for submit
                saveAndAdvance(OnboardingPatchRequest(step: "ssn"))
            }
        case 4:
            AlpacaAddressView(scale: scale, userPromptText: maskedSSN, animate: animate) { parsed in
                address = parsed.fullDisplay
                saveAndAdvance(OnboardingPatchRequest(
                    step: "address",
                    streetAddress: [parsed.streetAddress],
                    city: parsed.city,
                    state: parsed.state,
                    postalCode: parsed.postalCode
                ))
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
                animate: animate,
                initialSelected: citizenshipSelection.isEmpty ? nil : citizenshipSelection
            ) { value in
                citizenshipSelection = value
                saveAndAdvance(OnboardingPatchRequest(
                    step: "citizenship",
                    countryOfCitizenship: "USA",
                    countryOfBirth: "USA",
                    countryOfTaxResidence: "USA"
                ))
            }
        case 6:
            AlpacaEmploymentView(
                scale: scale,
                userPromptText: citizenshipSelection,
                animate: animate,
                initialStatus: employmentStatus,
                initialEmployer: employerName,
                initialJobTitle: jobTitle
            ) { status, employer, title in
                employmentStatus = status
                employerName = employer
                jobTitle = title
                saveAndAdvance(OnboardingPatchRequest(
                    step: "employment",
                    employmentInfo: [
                        "employment_status": OnboardingDataMapper.normalizeEmploymentStatus(status),
                        "employer_name": employer,
                        "job_title": title,
                    ]
                ))
            }
        case 7:
            AlpacaFundingSourceView(
                scale: scale,
                userPromptText: employmentStatus,
                animate: animate,
                initialSelected: fundingSources
            ) { sources in
                fundingSources = sources
                saveAndAdvance(OnboardingPatchRequest(
                    step: "funding_sources",
                    fundingSources: Array(sources).map { OnboardingDataMapper.normalizeFundingSource($0) }
                ))
            }
        case 8:
            AlpacaRegulatoryView(
                scale: scale,
                userPromptText: fundingSources.first ?? "",
                animate: animate
            ) { seniorOfficer, affiliated, political in
                saveAndAdvance(OnboardingPatchRequest(
                    step: "disclosures",
                    disclosures: [
                        "is_control_person": seniorOfficer,
                        "is_affiliated_exchange_or_finra": affiliated,
                        "is_politically_exposed": political,
                        "immediate_family_exposed": political,
                    ]
                ))
            }
        case 9:
            AlpacaAgreementsView(
                scale: scale,
                animate: animate
            ) { agreed in
                let now = OnboardingDataMapper.isoTimestamp()
                saveAndAdvance(OnboardingPatchRequest(
                    step: "agreements",
                    agreementsSigned: [
                        "customer_agreement": agreed ? "true" : "false",
                        "margin_agreement": agreed ? "true" : "false",
                        "signed_at": now,
                        "ip_address": "0.0.0.0",
                    ]
                ))
            }
        case 10:
            AlpacaSetupCompleteView(
                scale: scale,
                userName: userName,
                onSubmit: {
                    let response = try await onboarding.submit(taxId: ssnDigits)
                    print("[AlpacaSetup] KYC submitted: \(response.accountStatus)")
                },
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

    private func saveAndAdvance(_ request: OnboardingPatchRequest) {
        Task {
            do {
                try await onboarding.saveStep(request)
            } catch {
                print("[AlpacaSetup] Failed to save step \(request.step): \(error)")
            }
            advance()
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
    AlpacaSetupContainerView(userName: "Riley") {}
}
