import XCTest
@testable import Sevino

@MainActor
final class ContentViewModelTests: XCTestCase {

    private var mockOnboarding: MockOnboardingService!
    private var mockPhoneVerification: MockPhoneVerificationService!
    private var mockAuth: MockAuthService!
    private var viewModel: ContentViewModel!

    override func setUp() {
        mockOnboarding = MockOnboardingService()
        mockPhoneVerification = MockPhoneVerificationService()
        mockAuth = MockAuthService()
        // Default to a verified-email session so tests focused on phone /
        // onboarding behavior bypass the email gate.
        mockAuth.isEmailVerified = true
        mockAuth.currentEmail = "test@example.com"
        viewModel = ContentViewModel(
            onboardingService: mockOnboarding,
            phoneVerificationService: mockPhoneVerification,
            authService: mockAuth
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

    func testStartFreshSignUpFlowRoutesToEmailVerification() async {
        // Fresh Supabase email/password signup leaves `isEmailVerified == false`
        // since `signUp` returns before the user clicks the confirmation link.
        mockAuth.isEmailVerified = false

        await viewModel.startFreshSignUpFlow()

        XCTAssertEqual(viewModel.route, .emailVerification(email: "test@example.com"))
        XCTAssertEqual(mockOnboarding.getStatusCallCount, 0,
                       "fresh signup must not hit /onboarding/status — there's no server-side state to resume yet")
    }

    func testStartFreshSignUpFlowMissingEmailRoutesToStatusCheckFailed() async {
        mockAuth.isEmailVerified = false
        mockAuth.currentEmail = nil

        await viewModel.startFreshSignUpFlow()

        XCTAssertEqual(viewModel.route, .statusCheckFailed,
                       "missing session email is unexpected post-signup; bail safely instead of routing to .emailVerification with an empty string")
    }

    func testStartFreshSignUpFlowAlreadyVerifiedSkipsEmailGate() async {
        // Defensive against a future auto-verifying auth provider (OAuth, magic
        // link) — `EmailVerificationView` only advances on a `false → true`
        // transition, so already-verified users would otherwise stall there.
        mockAuth.isEmailVerified = true

        await viewModel.startFreshSignUpFlow()

        XCTAssertEqual(viewModel.route, .phone,
                       "an auto-verified fresh signup must skip the email gate, not get stuck on the OTP screen with no advance trigger")
    }

    // MARK: - savePhoneNumber

    func testSavePhoneNumberSuccessAdvancesToPhoneVerification() async {
        viewModel.onEmailVerified()

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
        viewModel.onEmailVerified()
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
        viewModel.onEmailVerified()
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
        viewModel.onEmailVerified()
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
        viewModel.onEmailVerified()
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

    // MARK: - Email verification transitions

    func testOnEmailVerifiedAdvancesToPhone() {
        viewModel.onEmailVerified()

        XCTAssertEqual(viewModel.route, .phone,
                       "post email verification, the user becomes eligible to enter their phone number")
    }

    func testCheckOnboardingStatusUnverifiedEmailRoutesToEmailVerification() async {
        mockAuth.isEmailVerified = false
        mockAuth.currentEmail = "unverified@example.com"

        await viewModel.checkOnboardingStatus()

        XCTAssertEqual(viewModel.route, .emailVerification(email: "unverified@example.com"))
        XCTAssertEqual(mockOnboarding.getStatusCallCount, 0,
                       "unverified email must short-circuit before hitting /onboarding/status — there's no resumeable state for an unconfirmed account")
    }

    func testCheckOnboardingStatusUnverifiedEmailMissingEmailRoutesToStatusCheckFailed() async {
        mockAuth.isEmailVerified = false
        mockAuth.currentEmail = nil

        await viewModel.checkOnboardingStatus()

        XCTAssertEqual(viewModel.route, .statusCheckFailed,
                       "an unverified session with no email is unrecoverable from the app's perspective; bail to retry rather than route to .emailVerification(email: \"\")")
    }

    func testCheckOnboardingStatusVerifiedEmailProceedsToBackend() async {
        // Pin the implicit assertion: a verified email must NOT short-circuit
        // the backend status fetch. Without this, regressing the gate to
        // accidentally always-true would silently break resume routing.
        mockAuth.isEmailVerified = true
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            onboardingCompleted: true,
            onboardingStep: nil,
            accountStatus: nil,
            profile: nil,
            financialProfile: nil,
            phoneVerified: true
        )

        await viewModel.checkOnboardingStatus()

        XCTAssertEqual(mockOnboarding.getStatusCallCount, 1,
                       "verified email must NOT short-circuit the backend status check")
        XCTAssertEqual(viewModel.route, .home)
    }

    // MARK: - Phone verification transitions

    func testOnPhoneVerifiedAdvancesToOnboarding() async {
        viewModel.onEmailVerified()
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "(416) 555-1234"))

        viewModel.onPhoneVerified()

        XCTAssertEqual(viewModel.route, .onboarding(step: 1, data: nil))
    }

    func testOnChangeNumberReturnsToPhone() async {
        viewModel.onEmailVerified()
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
        viewModel.onEmailVerified()
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
        viewModel.onEmailVerified()

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
        XCTAssertNotEqual(
            AuthenticatedRoute.emailVerification(email: "a@example.com"),
            AuthenticatedRoute.emailVerification(email: "b@example.com")
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
