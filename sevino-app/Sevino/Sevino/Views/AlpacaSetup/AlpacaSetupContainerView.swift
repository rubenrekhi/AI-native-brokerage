import SwiftUI

struct AlpacaSetupContainerView: View {
    let onComplete: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var viewModel: AlpacaSetupViewModel
    @State private var animate: Bool
    @State private var scale: CGFloat = 1

    init(
        userName: String,
        initialStep: Int = 1,
        resumeData: OnboardingResumeManager.AlpacaResumeData? = nil,
        onboardingService: any OnboardingServiceProtocol = OnboardingService.shared,
        onComplete: @escaping () -> Void
    ) {
        self.onComplete = onComplete
        let isResuming = resumeData != nil && initialStep > 1
        _viewModel = State(initialValue: AlpacaSetupViewModel(
            userName: userName,
            initialStep: initialStep,
            resumeData: resumeData,
            service: onboardingService
        ))
        _animate = State(initialValue: !isResuming)
    }

    var body: some View {
        VStack(spacing: 0) {
            if viewModel.currentStep > 1 {
                OnboardingProgressBar(
                    currentStep: viewModel.currentStep - 1,
                    totalSteps: AlpacaSetupViewModel.totalSteps - 1,
                    scale: scale
                )
                .padding(.top, 8 * scale)
                .padding(.horizontal, 32 * scale)
                .padding(.bottom, 8 * scale)

                if viewModel.currentStep == 10 {
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
        .onChange(of: viewModel.isComplete) { _, isComplete in
            if isComplete {
                onComplete()
            }
        }
    }


    @ViewBuilder
    private var backgroundView: some View {
        if viewModel.currentStep == 1 || viewModel.currentStep == 10 {
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
            AlpacaSetupIntroView(scale: scale, userName: viewModel.userName, animate: animate) {
                viewModel.submitKYCIntro()
            }
        case 2:
            AlpacaLegalNameView(scale: scale, animate: animate, initialName: viewModel.legalName) { name in
                viewModel.submitLegalName(name)
            }
        case 3:
            AlpacaSSNView(scale: scale, userPromptText: viewModel.legalName, animate: animate) { ssn in
                viewModel.submitSSN(ssn)
            }
        case 4:
            AlpacaAddressView(scale: scale, userPromptText: viewModel.maskedSSN, animate: animate) { parsed in
                viewModel.submitAddress(parsed)
            }
        case 5:
            OnboardingSingleSelectView(
                scale: scale,
                userPromptText: viewModel.address,
                response1: L10n.Onboarding.alpacaCitizenshipResponse1,
                response2: "",
                options: [
                    L10n.Onboarding.alpacaCitizenYes,
                    L10n.Onboarding.alpacaCitizenResident,
                    L10n.Onboarding.alpacaCitizenNo,
                ],
                animate: animate,
                initialSelected: viewModel.citizenshipSelection.isEmpty ? nil : viewModel.citizenshipSelection
            ) { value in
                viewModel.submitCitizenship(value)
            }
        case 6:
            AlpacaEmploymentView(
                scale: scale,
                userPromptText: viewModel.citizenshipSelection,
                animate: animate,
                initialStatus: viewModel.employmentStatus,
                initialEmployer: viewModel.employerName,
                initialJobTitle: viewModel.jobTitle
            ) { status, employer, title in
                viewModel.submitEmployment(status: status, employer: employer, title: title)
            }
        case 7:
            AlpacaFundingSourceView(
                scale: scale,
                userPromptText: viewModel.employmentStatus,
                animate: animate,
                initialSelected: viewModel.fundingSources
            ) { sources in
                viewModel.submitFundingSources(sources)
            }
        case 8:
            AlpacaRegulatoryView(
                scale: scale,
                userPromptText: viewModel.fundingSources.first ?? "",
                animate: animate
            ) { seniorOfficer, affiliated, political in
                viewModel.submitDisclosures(seniorOfficer: seniorOfficer, affiliated: affiliated, political: political)
            }
        case 9:
            AlpacaAgreementsView(
                scale: scale,
                animate: animate
            ) { agreed in
                viewModel.submitAgreements(agreed: agreed)
            }
        case 10:
            AlpacaSetupCompleteView(
                scale: scale,
                userName: viewModel.userName,
                onSubmit: {
                    try await viewModel.submitKYC(taxId: viewModel.ssnDigits)
                },
                onContinue: onComplete
            )
        default:
            Spacer()
        }
    }

    private func goBack() {
        if viewModel.currentStep > 1 {
            animate = false
            withAnimation(.easeInOut(duration: 0.3)) {
                viewModel.goBack()
            }
        }
    }
}


#Preview {
    AlpacaSetupContainerView(userName: "Riley") {}
}
