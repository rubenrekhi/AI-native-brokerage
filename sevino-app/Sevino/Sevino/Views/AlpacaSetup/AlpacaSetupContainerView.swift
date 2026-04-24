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
        SevinoGlassContainer {
            VStack(spacing: 0) {
                if viewModel.currentStep > 1 {
                    ProgressBar(
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
        }
        .background { backgroundView }
        .overlay(alignment: .bottom) { saveErrorBanner }
        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: viewModel.pendingRetryRequest?.step)
        .onChange(of: viewModel.error) { _, newError in
            if let newError {
                AccessibilityNotification.Announcement(
                    "\(L10n.Onboarding.alpacaSaveErrorHeading). \(newError)"
                ).post()
            }
        }
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
    private var saveErrorBanner: some View {
        if let message = viewModel.error, viewModel.pendingRetryRequest != nil {
            VStack(alignment: .leading, spacing: 8 * scale) {
                VStack(alignment: .leading, spacing: 8 * scale) {
                    Text(L10n.Onboarding.alpacaSaveErrorHeading)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeText)

                    Text(message)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.welcomeTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)

                HStack(spacing: 8 * scale) {
                    Button(action: viewModel.dismissSaveError) {
                        Text(L10n.Onboarding.alpacaSaveErrorDismiss)
                            .font(.system(size: 14 * scale, weight: .medium))
                            .foregroundStyle(Color.welcomeTextSecondary)
                            .padding(.horizontal, 16 * scale)
                            .padding(.vertical, 10 * scale)
                            .contentShape(Rectangle())
                            .frame(minHeight: 44)
                    }
                    .buttonStyle(.plain)
                    .modifier(SevinoGlass.nav)

                    Button(action: retry) {
                        HStack(spacing: 6 * scale) {
                            if viewModel.isLoading {
                                ProgressView()
                                    .tint(Color.welcomeText)
                                    .scaleEffect(0.8)
                            }
                            Text(L10n.Onboarding.alpacaSaveErrorRetry)
                                .font(.system(size: 14 * scale, weight: .semibold))
                                .foregroundStyle(Color.welcomeText)
                        }
                        .padding(.horizontal, 16 * scale)
                        .padding(.vertical, 10 * scale)
                        .contentShape(Rectangle())
                        .frame(minHeight: 44)
                    }
                    .buttonStyle(.plain)
                    .disabled(viewModel.isLoading)
                    .modifier(SevinoGlass.tintedButton(tint: Color.onboardingButtonActive))
                }
            }
            .padding(16 * scale)
            .frame(maxWidth: .infinity, alignment: .leading)
            .modifier(SevinoGlass.nav)
            .padding(.horizontal, 16 * scale)
            .padding(.bottom, 24 * scale)
            .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
        }
    }

    private func retry() {
        Task { await viewModel.retryLastSave() }
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
            AlpacaAddressView(
                scale: scale,
                userPromptText: viewModel.legalName,
                animate: animate,
                initialAddress: viewModel.initialParsedAddress
            ) { parsed in
                viewModel.submitAddress(parsed)
            }
        case 4:
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
        case 5:
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
        case 6:
            AlpacaFundingSourceView(
                scale: scale,
                userPromptText: viewModel.employmentStatus,
                animate: animate,
                initialSelected: viewModel.fundingSources
            ) { sources in
                viewModel.submitFundingSources(sources)
            }
        case 7:
            AlpacaSSNView(scale: scale, userPromptText: viewModel.fundingSources.first ?? "", animate: animate) { ssn in
                viewModel.submitSSN(ssn)
            }
        case 8:
            AlpacaRegulatoryView(
                scale: scale,
                userPromptText: viewModel.maskedSSN,
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
