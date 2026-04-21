import XCTest
@testable import Sevino

@MainActor
final class ContentViewModelTests: XCTestCase {

    private var mockOnboarding: MockOnboardingService!
    private var mockAuth: MockAuthService!
    private var viewModel: ContentViewModel!

    override func setUp() {
        mockOnboarding = MockOnboardingService()
        mockAuth = MockAuthService()
        viewModel = ContentViewModel(
            onboardingService: mockOnboarding,
            authService: mockAuth
        )
    }

    // MARK: - Initial state

    func testInitialState() {
        XCTAssertFalse(viewModel.isCheckingStatus)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertFalse(viewModel.showPhoneSheet)
        XCTAssertFalse(viewModel.showOnboarding)
        XCTAssertFalse(viewModel.showAlpacaSetup)
        XCTAssertFalse(viewModel.statusCheckFailed)
        XCTAssertFalse(viewModel.showPhoneError)
        XCTAssertEqual(viewModel.onboardingUserName, "")
        XCTAssertNil(viewModel.onboardingResumeData)
        XCTAssertNil(viewModel.alpacaResumeData)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - startFreshSignUpFlow

    func testStartFreshSignUpFlowSkipsStatusCheck() {
        viewModel.startFreshSignUpFlow()

        XCTAssertTrue(viewModel.showPhoneSheet)
        XCTAssertTrue(viewModel.showOnboarding)
        XCTAssertEqual(mockOnboarding.getStatusCallCount, 0)
    }

    // MARK: - savePhoneNumber

    func testSavePhoneNumberSuccessDismissesSheet() async {
        viewModel.startFreshSignUpFlow()

        await viewModel.savePhoneNumber("4165551234")

        XCTAssertFalse(viewModel.showPhoneSheet)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(mockOnboarding.savedSteps.count, 1)
        XCTAssertEqual(mockOnboarding.savedSteps.last?.step, "welcome")
        XCTAssertEqual(mockOnboarding.savedSteps.last?.phoneNumber, "4165551234")
    }

    func testSavePhoneNumberFailureKeepsSheetAndRecordsError() async {
        viewModel.startFreshSignUpFlow()
        mockOnboarding.saveStepError = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.savePhoneNumber("4165551234")

        XCTAssertTrue(viewModel.showPhoneSheet, "sheet stays open so user can retry after seeing the alert")
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
        XCTAssertFalse(viewModel.showPhoneSheet)
        XCTAssertNil(viewModel.error)
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

        XCTAssertFalse(viewModel.showOnboarding)
        XCTAssertFalse(viewModel.showAlpacaSetup)
        XCTAssertFalse(viewModel.isCheckingStatus)
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

        XCTAssertTrue(viewModel.showOnboarding)
        XCTAssertFalse(viewModel.showAlpacaSetup)
        XCTAssertEqual(viewModel.onboardingResumeStep, 3)
        XCTAssertEqual(viewModel.onboardingUserName, "Riley")
        XCTAssertNotNil(viewModel.onboardingResumeData)
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

        XCTAssertTrue(viewModel.showAlpacaSetup)
        XCTAssertFalse(viewModel.showOnboarding)
        XCTAssertEqual(viewModel.alpacaResumeStep, 1)
        XCTAssertNotNil(viewModel.alpacaResumeData)
    }

    func testCheckOnboardingStatusSurfacesRetryOnError() async {
        mockOnboarding.statusError = URLError(.notConnectedToInternet)

        await viewModel.checkOnboardingStatus()

        XCTAssertFalse(viewModel.isCheckingStatus, "defer must reset flag even on error")
        XCTAssertTrue(viewModel.statusCheckFailed, "view needs a flag to show a retry prompt")
        XCTAssertNotNil(viewModel.error)
    }

    func testCheckOnboardingStatusRetryClearsFailureFlagOnSuccess() async {
        mockOnboarding.statusError = URLError(.notConnectedToInternet)
        await viewModel.checkOnboardingStatus()
        XCTAssertTrue(viewModel.statusCheckFailed)

        mockOnboarding.statusError = nil
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            onboardingCompleted: true,
            onboardingStep: nil,
            accountStatus: nil,
            profile: nil,
            financialProfile: nil
        )
        await viewModel.checkOnboardingStatus()

        XCTAssertFalse(viewModel.statusCheckFailed)
        XCTAssertNil(viewModel.error)
    }

    // MARK: - Flow transitions

    func testCompleteOnboardingAdvancesToAlpacaSetup() {
        viewModel.startFreshSignUpFlow()

        viewModel.completeOnboarding(userName: "Riley")

        XCTAssertFalse(viewModel.showOnboarding)
        XCTAssertTrue(viewModel.showAlpacaSetup)
        XCTAssertEqual(viewModel.onboardingUserName, "Riley")
        XCTAssertEqual(viewModel.alpacaResumeStep, 1)
        XCTAssertNil(viewModel.alpacaResumeData, "Alpaca resume data resets on fresh handoff")
    }

    func testCompleteAlpacaSetupClearsFlag() {
        viewModel.completeOnboarding(userName: "Riley")

        viewModel.completeAlpacaSetup()

        XCTAssertFalse(viewModel.showAlpacaSetup)
    }

    // MARK: - signOut

    func testSignOutResetsRoutingState() async {
        viewModel.startFreshSignUpFlow()
        viewModel.completeOnboarding(userName: "Riley")
        mockAuth.isAuthenticated = true

        await viewModel.signOut()

        XCTAssertFalse(viewModel.showPhoneSheet)
        XCTAssertFalse(viewModel.showOnboarding)
        XCTAssertFalse(viewModel.showAlpacaSetup)
        XCTAssertNil(viewModel.onboardingResumeData)
        XCTAssertNil(viewModel.alpacaResumeData)
        XCTAssertFalse(mockAuth.isAuthenticated)
    }

    func testSignOutFailureStillResetsRoutingState() async {
        viewModel.startFreshSignUpFlow()
        mockAuth.errorToThrow = NSError(
            domain: "", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Sign-out failed"]
        )

        await viewModel.signOut()

        XCTAssertFalse(viewModel.showPhoneSheet)
        XCTAssertFalse(viewModel.showOnboarding)
        XCTAssertEqual(viewModel.error, "Sign-out failed")
    }
}
