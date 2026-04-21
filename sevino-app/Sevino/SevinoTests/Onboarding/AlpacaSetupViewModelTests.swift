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
        data.address = "123 Main St"
        data.employmentStatus = "employed"

        let vm = AlpacaSetupViewModel(userName: "Jane", initialStep: 4, resumeData: data, service: mock)

        XCTAssertEqual(vm.currentStep, 4)
        XCTAssertEqual(vm.legalName, "Jane Doe")
        XCTAssertEqual(vm.address, "123 Main St")
        XCTAssertEqual(vm.employmentStatus, "employed")
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

    func testSaveAndAdvanceOnFailureRecordsErrorButStillAdvances() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "Network down"])

        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))

        XCTAssertEqual(viewModel.error, "Network down")
        XCTAssertEqual(viewModel.currentStep, 2)
        XCTAssertFalse(viewModel.isLoading)
    }

    func testSaveAndAdvanceClearsPreviousError() async {
        mock.saveStepError = NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "First error"])
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "kyc_intro"))
        XCTAssertNotNil(viewModel.error)

        mock.saveStepError = nil
        await viewModel.saveAndAdvance(OnboardingPatchRequest(step: "legal_name"))

        XCTAssertNil(viewModel.error)
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
        // Expected
    }
}
