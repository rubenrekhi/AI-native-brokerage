import XCTest
@testable import Sevino

@MainActor
final class OnboardingServiceTests: XCTestCase {

    private var mockAPI: MockAPIClient!
    private var service: OnboardingService!

    override func setUp() {
        mockAPI = MockAPIClient()
        service = OnboardingService(api: mockAPI)
    }

    // MARK: - saveStep

    func testSaveStepCallsPatchWithCorrectPath() async throws {
        mockAPI.responseToReturn = OnboardingPatchResponse(step: "preferred_name")

        try await service.saveStep(OnboardingPatchRequest(step: "preferred_name", preferredName: "Riley"))

        XCTAssertEqual(mockAPI.lastPath, "/v1/onboarding")
        XCTAssertEqual(mockAPI.lastMethod, "PATCH")
    }

    func testSaveStepPropagatesErrors() async {
        mockAPI.errorToThrow = APIError(error: "Not authenticated", code: "AUTHENTICATION_ERROR")

        do {
            try await service.saveStep(OnboardingPatchRequest(step: "preferred_name"))
            XCTFail("Expected error to be thrown")
        } catch {
            XCTAssertTrue(error is APIError)
        }
    }

    // MARK: - submit

    func testSubmitCallsPostWithCorrectPath() async throws {
        mockAPI.responseToReturn = OnboardingSubmitResponse(
            accountStatus: "SUBMITTED",
            alpacaAccountId: "alpaca-123"
        )

        let response = try await service.submit(taxId: "123-45-6789")

        XCTAssertEqual(mockAPI.lastPath, "/v1/onboarding/submit")
        XCTAssertEqual(mockAPI.lastMethod, "POST")
        XCTAssertEqual(response.accountStatus, "SUBMITTED")
        XCTAssertEqual(response.alpacaAccountId, "alpaca-123")
    }

    func testSubmitPropagatesErrors() async {
        mockAPI.errorToThrow = APIError(error: "Incomplete", code: "INCOMPLETE_ONBOARDING")

        do {
            _ = try await service.submit(taxId: "123-45-6789")
            XCTFail("Expected error to be thrown")
        } catch {
            XCTAssertTrue(error is APIError)
        }
    }

    // MARK: - getStatus

    func testGetStatusCallsGetWithCorrectPath() async throws {
        mockAPI.responseToReturn = OnboardingStatusResponse(
            onboardingCompleted: false,
            onboardingStep: "preferred_name",
            accountStatus: nil,
            profile: nil,
            financialProfile: nil
        )

        let response = try await service.getStatus()

        XCTAssertEqual(mockAPI.lastPath, "/v1/onboarding/status")
        XCTAssertEqual(mockAPI.lastMethod, "GET")
        XCTAssertFalse(response.onboardingCompleted)
        XCTAssertEqual(response.onboardingStep, "preferred_name")
    }

    func testGetStatusPropagatesErrors() async {
        mockAPI.errorToThrow = URLError(.notConnectedToInternet)

        do {
            _ = try await service.getStatus()
            XCTFail("Expected error to be thrown")
        } catch {
            XCTAssertTrue(error is URLError)
        }
    }
}
