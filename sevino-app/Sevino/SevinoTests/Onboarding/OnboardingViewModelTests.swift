import XCTest
@testable import Sevino

@MainActor
final class OnboardingViewModelTests: XCTestCase {

    private var mock: MockOnboardingService!
    private var viewModel: OnboardingViewModel!

    override func setUp() {
        mock = MockOnboardingService()
        viewModel = OnboardingViewModel(service: mock)
    }

    // MARK: - saveAndAdvance

    func testSaveAndAdvanceSavesAndAdvancesStep() async {
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))

        XCTAssertEqual(mock.savedSteps.count, 1)
        XCTAssertEqual(mock.savedSteps.first?.step, "welcome")
        XCTAssertEqual(viewModel.currentStep, 2)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.pendingRetryRequest)
    }

    func testSaveAndAdvanceOnFailureRecordsErrorAndDoesNotAdvance() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])

        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))

        XCTAssertEqual(viewModel.error, "Network down")
        XCTAssertEqual(viewModel.currentStep, 1)
        XCTAssertEqual(viewModel.pendingRetryRequest?.step, "welcome")
        XCTAssertFalse(viewModel.isLoading)
    }

    func testSaveAndAdvanceClearsPreviousErrorOnSuccess() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "First error"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))
        XCTAssertNotNil(viewModel.error)

        mock.saveStepError = nil
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))

        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.pendingRetryRequest)
        XCTAssertEqual(viewModel.currentStep, 2)
    }

    // MARK: - retryLastSave / dismissSaveError

    func testRetryLastSaveResendsFailedRequestAndAdvancesOnSuccess() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))
        XCTAssertEqual(viewModel.currentStep, 1)

        mock.saveStepError = nil
        await viewModel.retryLastSave()

        XCTAssertEqual(mock.savedSteps.map(\.step), ["welcome", "welcome"])
        XCTAssertEqual(viewModel.currentStep, 2)
        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.pendingRetryRequest)
    }

    func testRetryLastSaveWithNoPendingRequestIsNoOp() async {
        await viewModel.retryLastSave()

        XCTAssertEqual(mock.savedSteps.count, 0)
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    func testRetryLastSaveOnRepeatedFailureKeepsBannerState() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Still down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))

        await viewModel.retryLastSave()

        XCTAssertEqual(mock.savedSteps.count, 2)
        XCTAssertEqual(viewModel.error, "Still down")
        XCTAssertEqual(viewModel.pendingRetryRequest?.step, "welcome")
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    func testDismissSaveErrorClearsErrorAndPendingRetryWithoutAdvancing() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))
        XCTAssertNotNil(viewModel.error)
        XCTAssertNotNil(viewModel.pendingRetryRequest)

        viewModel.dismissSaveError()

        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.pendingRetryRequest)
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    // MARK: - goBack interaction with save error

    func testGoBackDismissesPendingSaveError() async {
        let vm = OnboardingViewModel(initialStep: 2, service: mock)
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await vm.saveAndAdvance(OnboardingPatchRequest(step: "preferred_name", preferredName: "Riley"))
        XCTAssertNotNil(vm.pendingRetryRequest)

        vm.goBack()

        XCTAssertNil(vm.error)
        XCTAssertNil(vm.pendingRetryRequest)
        XCTAssertEqual(vm.currentStep, 1)
    }

    func testGoBackAtStep1LeavesPendingErrorIntact() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "welcome"))

        viewModel.goBack()

        XCTAssertEqual(viewModel.error, "Network down")
        XCTAssertEqual(viewModel.pendingRetryRequest?.step, "welcome")
        XCTAssertEqual(viewModel.currentStep, 1)
    }
}
