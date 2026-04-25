import XCTest
@testable import Sevino

@MainActor
final class ContentViewModelTests: XCTestCase {

    private var mockOnboarding: MockOnboardingService!
    private var viewModel: ContentViewModel!

    override func setUp() {
        mockOnboarding = MockOnboardingService()
        viewModel = ContentViewModel(onboardingService: mockOnboarding)
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

        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "4165551234"))
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(mockOnboarding.savedSteps.count, 1)
        XCTAssertEqual(mockOnboarding.savedSteps.last?.step, "welcome")
        XCTAssertEqual(mockOnboarding.savedSteps.last?.phoneNumber, "4165551234")
    }

    func testSavePhoneNumberFailureKeepsPhoneRouteAndRecordsError() async {
        viewModel.startFreshSignUpFlow()
        mockOnboarding.saveStepError = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.savePhoneNumber("4165551234")

        XCTAssertEqual(viewModel.route, .phone, "route stays on phone so user can retry")
        XCTAssertTrue(viewModel.showPhoneError, "alert flag is set so the view presents an alert")
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertEqual(viewModel.error, "Network error")
    }

    func testSavePhoneNumberRetrySuccessClearsErrorFlag() async {
        viewModel.startFreshSignUpFlow()
        mockOnboarding.saveStepError = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertTrue(viewModel.showPhoneError)

        mockOnboarding.saveStepError = nil
        await viewModel.savePhoneNumber("4165551234")

        XCTAssertFalse(viewModel.showPhoneError)
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "4165551234"))
        XCTAssertNil(viewModel.error)
    }

    // MARK: - Phone verification transitions

    func testOnPhoneVerifiedAdvancesToOnboarding() async {
        viewModel.startFreshSignUpFlow()
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "4165551234"))

        viewModel.onPhoneVerified()

        XCTAssertEqual(viewModel.route, .onboarding(step: 1, data: nil))
    }

    func testOnChangeNumberReturnsToPhone() async {
        viewModel.startFreshSignUpFlow()
        await viewModel.savePhoneNumber("4165551234")
        XCTAssertEqual(viewModel.route, .phoneVerification(phoneNumber: "4165551234"))

        viewModel.onChangeNumber()

        XCTAssertEqual(viewModel.route, .phone)
    }

    func testClearErrorResetsErrorAndAlertFlag() async {
        mockOnboarding.saveStepError = NSError(
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
            financialProfile: nil
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
            financialProfile: nil
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
            financialProfile: nil
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
            financialProfile: nil
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
