import XCTest
@testable import Sevino

@MainActor
final class ContentViewModelTests: XCTestCase {

    private var mockOnboarding: MockOnboardingService!
    private var mockPhoneVerification: MockPhoneVerificationService!
    private var viewModel: ContentViewModel!

    override func setUp() {
        mockOnboarding = MockOnboardingService()
        mockPhoneVerification = MockPhoneVerificationService()
        viewModel = ContentViewModel(
            onboardingService: mockOnboarding,
            phoneVerificationService: mockPhoneVerification
        )
    }

    // MARK: - Initial state

    func testInitialState() {
        XCTAssertEqual(viewModel.route, .idle, "pre-check state is distinct from .home so cold launch does not flash HomeView")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertFalse(viewModel.showPhoneError)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - startFreshSignUpFlow

    func testStartFreshSignUpFlowSkipsStatusCheck() {
        viewModel.startFreshSignUpFlow()

        XCTAssertEqual(viewModel.route, .phone)
        XCTAssertEqual(mockOnboarding.getStatusCallCount, 0)
    }

    // MARK: - savePhoneNumber

    func testSavePhoneNumberSuccessAdvancesToPhoneVerification() async {
        viewModel.startFreshSignUpFlow()

        await viewModel.savePhoneNumber("4165551234")

        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "(416) 555-1234"))
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(mockPhoneVerification.sentPhoneNumbers, ["4165551234"],
                       "OTP must be dispatched before navigation so the user lands on the verification screen with a code on the way")
        XCTAssertTrue(mockOnboarding.savedSteps.isEmpty,
                      "phone-entry no longer writes user_profiles — the verified phone is persisted server-side by /v1/auth/phone/confirm (SEV-448)")
    }

    func testSavePhoneNumberSendOTPFailureKeepsPhoneRoute() async {
        viewModel.startFreshSignUpFlow()
        mockPhoneVerification.sendOTPError = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "SMS provider down"]
        )

        await viewModel.savePhoneNumber("4165551234")

        XCTAssertEqual(viewModel.route, .phone,
                       "send-OTP failure must NOT advance — the verification screen would be unusable without a code on the way")
        XCTAssertTrue(viewModel.showPhoneError)
        XCTAssertEqual(viewModel.error, "SMS provider down")
        XCTAssertTrue(mockOnboarding.savedSteps.isEmpty,
                      "no PATCH ever fires from phone capture — only the OTP send")
    }

    func testSavePhoneNumberPhoneTakenShowsLocalizedMessage() async {
        viewModel.startFreshSignUpFlow()
        mockPhoneVerification.sendOTPError = APIError(
            error: "ignored backend message",
            code: "PHONE_NUMBER_TAKEN"
        )

        await viewModel.savePhoneNumber("4165551234")

        XCTAssertEqual(viewModel.route, .phone,
                       "duplicate-phone keeps user on the entry screen so they can pick a different number")
        XCTAssertTrue(viewModel.showPhoneError)
        XCTAssertEqual(viewModel.error, L10n.Auth.phoneNumberTaken,
                       "PHONE_NUMBER_TAKEN gets the dedicated copy, not the generic backend message")
    }

    func testSavePhoneNumberRetrySuccessClearsErrorFlag() async {
        viewModel.startFreshSignUpFlow()
        mockPhoneVerification.sendOTPError = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertTrue(viewModel.showPhoneError)

        mockPhoneVerification.sendOTPError = nil
        await viewModel.savePhoneNumber("4165551234")

        XCTAssertFalse(viewModel.showPhoneError)
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "(416) 555-1234"))
        XCTAssertNil(viewModel.error)
    }

    func testSavePhoneNumberPhoneTakenThenRetryWithNewNumberAdvances() async {
        viewModel.startFreshSignUpFlow()
        mockPhoneVerification.sendOTPError = APIError(
            error: "ignored backend message",
            code: "PHONE_NUMBER_TAKEN"
        )
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertEqual(viewModel.route, .phone)
        XCTAssertEqual(viewModel.error, L10n.Auth.phoneNumberTaken)

        mockPhoneVerification.sendOTPError = nil
        await viewModel.savePhoneNumber("4165559999")

        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "(416) 555-9999"))
        XCTAssertNil(viewModel.error)
        XCTAssertFalse(viewModel.showPhoneError)
        XCTAssertEqual(mockPhoneVerification.sentPhoneNumbers.last, "4165559999",
                       "OTP must be dispatched against the new number after the duplicate-phone retry")
    }

    // MARK: - Phone verification transitions

    func testOnPhoneVerifiedAdvancesToOnboarding() async {
        viewModel.startFreshSignUpFlow()
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "(416) 555-1234"))

        viewModel.onPhoneVerified()

        XCTAssertEqual(viewModel.route, .onboarding(step: 1, data: nil))
    }

    func testOnChangeNumberReturnsToPhone() async {
        viewModel.startFreshSignUpFlow()
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "(416) 555-1234"))

        viewModel.onChangeNumber()

        XCTAssertEqual(viewModel.route, .phone)
    }

    func testClearErrorResetsErrorAndAlertFlag() async {
        mockPhoneVerification.sendOTPError = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )
        viewModel.startFreshSignUpFlow()
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertNotNil(viewModel.error)
        XCTAssertTrue(viewModel.showPhoneError)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
        XCTAssertFalse(viewModel.showPhoneError)
    }

    // MARK: - checkOnboardingStatus — destination routing

    func testCheckOnboardingStatusRoutesToHomeWhenCompleted() async {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            onboardingCompleted: true,
            onboardingStep: nil,
            accountStatus: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )

        await viewModel.checkOnboardingStatus()

        XCTAssertEqual(viewModel.route, .home)
    }

    func testCheckOnboardingStatusRoutesToOnboardingForPartialProgress() async {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "preferred_name",
            accountStatus: nil,
            profile: ProfileData(preferredName: "Riley"),
            financialProfile: nil,
            phoneVerified: true
        )

        await viewModel.checkOnboardingStatus()

        guard case .onboarding(let step, let data) = viewModel.route else {
            return XCTFail("expected onboarding route, got \(viewModel.route)")
        }
        XCTAssertEqual(step, 3)
        XCTAssertEqual(data?.userName, "Riley")
    }

    func testCheckOnboardingStatusRoutesToAlpacaSetupAfterPhase1() async {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "risk_disclosure",
            accountStatus: nil,
            profile: ProfileData(preferredName: "Riley"),
            financialProfile: nil,
            phoneVerified: true
        )

        await viewModel.checkOnboardingStatus()

        guard case .alpacaSetup(let step, let userName, let data) = viewModel.route else {
            return XCTFail("expected alpacaSetup route, got \(viewModel.route)")
        }
        XCTAssertEqual(step, 1)
        XCTAssertEqual(userName, "Riley")
        XCTAssertNotNil(data)
    }

    func testCheckOnboardingStatusSurfacesRetryOnError() async {
        mockOnboarding.statusError = URLError(.notConnectedToInternet)

        await viewModel.checkOnboardingStatus()

        // Regression guard: the catch branch must replace .loading with
        // .statusCheckFailed so an error can never leave the route stuck on .loading.
        XCTAssertEqual(viewModel.route, .statusCheckFailed, "view needs a route to show a retry prompt")
        XCTAssertNotNil(viewModel.error)
    }

    func testCheckOnboardingStatusRetryClearsFailureFlagOnSuccess() async {
        mockOnboarding.statusError = URLError(.notConnectedToInternet)
        await viewModel.checkOnboardingStatus()
        XCTAssertEqual(viewModel.route, .statusCheckFailed)

        mockOnboarding.statusError = nil
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            onboardingCompleted: true,
            onboardingStep: nil,
            accountStatus: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )
        await viewModel.checkOnboardingStatus()

        XCTAssertEqual(viewModel.route, .home)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - Flow transitions

    func testCompleteOnboardingAdvancesToAlpacaSetup() {
        viewModel.startFreshSignUpFlow()

        viewModel.completeOnboarding(userName: "Riley")

        guard case .alpacaSetup(let step, let userName, let data) = viewModel.route else {
            return XCTFail("expected alpacaSetup route, got \(viewModel.route)")
        }
        XCTAssertEqual(step, 1)
        XCTAssertEqual(userName, "Riley")
        XCTAssertNil(data, "fresh handoff passes nil resume data so containers treat it as a fresh flow")
    }

    func testCompleteAlpacaSetupRoutesHome() {
        viewModel.completeOnboarding(userName: "Riley")

        viewModel.completeAlpacaSetup()

        XCTAssertEqual(viewModel.route, .home)
    }

    // MARK: - Route equality

    func testRouteEqualityDiscriminatesAssociatedValues() {
        XCTAssertNotEqual(
            AuthenticatedRoute.onboarding(step: 1, data: nil),
            AuthenticatedRoute.onboarding(step: 2, data: nil)
        )
        XCTAssertNotEqual(
            AuthenticatedRoute.alpacaSetup(step: 1, userName: "A", data: nil),
            AuthenticatedRoute.alpacaSetup(step: 1, userName: "B", data: nil)
        )
        XCTAssertNotEqual(
            AuthenticatedRoute.phoneVerification(phoneNumber: "(555) 123-4567"),
            AuthenticatedRoute.phoneVerification(phoneNumber: "(555) 999-0000")
        )
        var dataA = OnboardingResumeManager.OnboardingResumeData()
        dataA.userName = "A"
        var dataB = OnboardingResumeManager.OnboardingResumeData()
        dataB.userName = "B"
        XCTAssertNotEqual(
            AuthenticatedRoute.onboarding(step: 1, data: dataA),
            AuthenticatedRoute.onboarding(step: 1, data: dataB)
        )
    }

}
