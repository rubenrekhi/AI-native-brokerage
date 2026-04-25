import XCTest
@testable import Sevino

@MainActor
final class AlpacaSetupViewModelTests: XCTestCase {

    private var mock: MockOnboardingService!
    private var viewModel: AlpacaSetupViewModel!

    override func setUp() {
        mock = MockOnboardingService()
        viewModel = AlpacaSetupViewModel(userName: "Riley", service: mock)
    }

    // MARK: - Initial state

    func testInitialStateUsesDefaults() {
        XCTAssertEqual(viewModel.currentStep, 1)
        XCTAssertFalse(viewModel.isComplete)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
        XCTAssertEqual(viewModel.userName, "Riley")
        XCTAssertEqual(viewModel.legalName, "")
        XCTAssertEqual(viewModel.ssnDigits, "")
    }

    func testInitialStateHydratesFromResumeData() {
        var data = OnboardingResumeManager.AlpacaResumeData()
        data.legalName = "Jane Doe"
        data.address = "123 Main St, New York, NY, 10001"
        data.streetAddress = "123 Main St"
        data.city = "New York"
        data.state = "NY"
        data.postalCode = "10001"
        data.employmentStatus = "employed"

        let vm = AlpacaSetupViewModel(userName: "Jane", initialStep: 4, resumeData: data, service: mock)

        XCTAssertEqual(vm.currentStep, 4)
        XCTAssertEqual(vm.legalName, "Jane Doe")
        XCTAssertEqual(vm.address, "123 Main St, New York, NY, 10001")
        XCTAssertEqual(vm.streetAddress, "123 Main St")
        XCTAssertEqual(vm.city, "New York")
        XCTAssertEqual(vm.state, "NY")
        XCTAssertEqual(vm.postalCode, "10001")
        XCTAssertEqual(vm.employmentStatus, "employed")

        let parsed = vm.initialParsedAddress
        XCTAssertNotNil(parsed)
        XCTAssertEqual(parsed?.streetAddress, "123 Main St")
        XCTAssertEqual(parsed?.city, "New York")
        XCTAssertEqual(parsed?.state, "NY")
        XCTAssertEqual(parsed?.postalCode, "10001")
        XCTAssertEqual(parsed?.fullDisplay, "123 Main St, New York, NY, 10001")
    }

    func testInitialParsedAddressIsNilWhenPartialDataPresent() {
        var data = OnboardingResumeManager.AlpacaResumeData()
        data.city = "New York"
        // street/state/postal missing

        let vm = AlpacaSetupViewModel(userName: "Jane", initialStep: 3, resumeData: data, service: mock)

        XCTAssertNil(vm.initialParsedAddress, "Partial address data must fall back to blank entry")
    }

    func testSubmitAddressWritesStructuredPartsAndRoundTripsThroughInitialParsedAddress() async {
        let parsed = ParsedAddress(
            streetAddress: "456 Elm Ave",
            city: "Brooklyn",
            state: "NY",
            postalCode: "11201",
            fullDisplay: "456 Elm Ave, Brooklyn, NY, 11201"
        )

        viewModel.submitAddress(parsed)
        // Drain the Task spawned inside submitAddress.
        await Task.yield()

        XCTAssertEqual(viewModel.address, "456 Elm Ave, Brooklyn, NY, 11201")
        XCTAssertEqual(viewModel.streetAddress, "456 Elm Ave")
        XCTAssertEqual(viewModel.city, "Brooklyn")
        XCTAssertEqual(viewModel.state, "NY")
        XCTAssertEqual(viewModel.postalCode, "11201")

        let round = viewModel.initialParsedAddress
        XCTAssertEqual(round?.streetAddress, parsed.streetAddress)
        XCTAssertEqual(round?.city, parsed.city)
        XCTAssertEqual(round?.state, parsed.state)
        XCTAssertEqual(round?.postalCode, parsed.postalCode)
        XCTAssertEqual(round?.fullDisplay, parsed.fullDisplay)
    }

    // MARK: - Navigation

    func testGoBackDecrementsStep() {
        let vm = AlpacaSetupViewModel(userName: "Riley", initialStep: 3, service: mock)
        vm.goBack()
        XCTAssertEqual(vm.currentStep, 2)
    }

    func testGoBackAtStep1DoesNothing() {
        viewModel.goBack()
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    func testAdvanceAtFinalStepMarksComplete() {
        let vm = AlpacaSetupViewModel(userName: "Riley", initialStep: AlpacaSetupViewModel.totalSteps, service: mock)
        vm.advance()
        XCTAssertTrue(vm.isComplete)
        XCTAssertEqual(vm.currentStep, AlpacaSetupViewModel.totalSteps)
    }

    // MARK: - saveAndAdvance

    func testSaveAndAdvanceSavesAndAdvancesStep() async {
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))

        XCTAssertEqual(mock.savedSteps.count, 1)
        XCTAssertEqual(mock.savedSteps.first?.step, "kyc_intro")
        XCTAssertEqual(viewModel.currentStep, 2)
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testSaveAndAdvanceOnFailureRecordsErrorAndDoesNotAdvance() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])

        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))

        XCTAssertEqual(viewModel.error, "Network down")
        XCTAssertEqual(viewModel.currentStep, 1)
        XCTAssertEqual(viewModel.pendingRetryRequest?.step, "kyc_intro")
        XCTAssertFalse(viewModel.isLoading)
    }

    func testSaveAndAdvanceClearsPreviousError() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "First error"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))
        XCTAssertNotNil(viewModel.error)

        mock.saveStepError = nil
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))

        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.pendingRetryRequest)
        XCTAssertEqual(viewModel.currentStep, 2)
    }

    // MARK: - retryLastSave / dismissSaveError

    func testRetryLastSaveResendsFailedRequestAndAdvancesOnSuccess() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))
        XCTAssertEqual(viewModel.currentStep, 1)

        mock.saveStepError = nil
        await viewModel.retryLastSave()

        XCTAssertEqual(mock.savedSteps.map(\.step), ["kyc_intro", "kyc_intro"])
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
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))

        await viewModel.retryLastSave()

        XCTAssertEqual(mock.savedSteps.count, 2)
        XCTAssertEqual(viewModel.error, "Still down")
        XCTAssertEqual(viewModel.pendingRetryRequest?.step, "kyc_intro")
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    // MARK: - goBack interaction with save error

    func testGoBackDismissesPendingSaveError() async {
        let vm = AlpacaSetupViewModel(userName: "Riley", initialStep: 2, service: mock)
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await vm.saveAndAdvance(OnboardingPatchRequest(step: "legal_name"))
        XCTAssertNotNil(vm.pendingRetryRequest)

        vm.goBack()

        XCTAssertNil(vm.error)
        XCTAssertNil(vm.pendingRetryRequest)
        XCTAssertEqual(vm.currentStep, 1)
    }

    func testGoBackAtStep1LeavesPendingErrorIntact() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))

        viewModel.goBack()

        XCTAssertEqual(viewModel.error, "Network down")
        XCTAssertEqual(viewModel.pendingRetryRequest?.step, "kyc_intro")
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    func testDismissSaveErrorClearsErrorAndPendingRetryWithoutAdvancing() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))
        XCTAssertNotNil(viewModel.error)
        XCTAssertNotNil(viewModel.pendingRetryRequest)

        viewModel.dismissSaveError()

        XCTAssertNil(viewModel.error)
        XCTAssertNil(viewModel.pendingRetryRequest)
        XCTAssertEqual(viewModel.currentStep, 1)
    }

    // MARK: - submitKYC

    func testSubmitKYCSuccessPassesTaxIdAndClearsError() async throws {
        try await viewModel.submitKYC(taxId: "123456789")

        XCTAssertEqual(mock.submittedTaxIds, ["123456789"])
        XCTAssertFalse(viewModel.isLoading)
        XCTAssertNil(viewModel.error)
    }

    func testSubmitKYCFailureRecordsErrorAndRethrows() async {
        let thrown = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "KYC rejected"])
        mock.submitError = thrown

        await XCTAssertThrowsErrorAsync(try await viewModel.submitKYC(taxId: "123"))

        XCTAssertEqual(viewModel.error, "KYC rejected")
        XCTAssertFalse(viewModel.isLoading)
    }
}

// MARK: - Helpers

private func XCTAssertThrowsErrorAsync<T>(
    _ expression: @autoclosure () async throws -> T,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        _ = try await expression()
        XCTFail("Expected error to be thrown", file: file, line: line)
    } catch {
    }
}
