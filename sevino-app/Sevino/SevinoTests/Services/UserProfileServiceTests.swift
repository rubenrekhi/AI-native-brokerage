import XCTest
@testable import Sevino

@MainActor
final class UserProfileServiceTests: XCTestCase {

    private var mockOnboarding: MockOnboardingService!
    private var service: UserProfileService!

    override func setUp() {
        mockOnboarding = MockOnboardingService()
        service = UserProfileService(onboardingService: mockOnboarding)
    }

    func testReturnsPreferredNameWhenPresent() async throws {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            profile: ProfileData(preferredName: "Riley", firstName: "Rileigh")
        )

        let name = try await service.fetchPreferredName()

        XCTAssertEqual(name, "Riley", "preferredName should take priority over firstName")
    }

    func testFallsBackToFirstNameWhenPreferredNameIsNil() async throws {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            profile: ProfileData(preferredName: nil, firstName: "Riley")
        )

        let name = try await service.fetchPreferredName()

        XCTAssertEqual(name, "Riley")
    }

    func testFallsBackToFirstNameWhenPreferredNameIsEmpty() async throws {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            profile: ProfileData(preferredName: "", firstName: "Riley")
        )

        let name = try await service.fetchPreferredName()

        XCTAssertEqual(name, "Riley", "empty preferredName should be treated as missing")
    }

    func testReturnsNilWhenBothNamesAreNil() async throws {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            profile: ProfileData(preferredName: nil, firstName: nil)
        )

        let name = try await service.fetchPreferredName()

        XCTAssertNil(name)
    }

    func testReturnsNilWhenBothNamesAreEmpty() async throws {
        mockOnboarding.statusResponse = OnboardingStatusResponse(
            profile: ProfileData(preferredName: "", firstName: "")
        )

        let name = try await service.fetchPreferredName()

        XCTAssertNil(name)
    }

    func testReturnsNilWhenProfileIsMissing() async throws {
        mockOnboarding.statusResponse = OnboardingStatusResponse(profile: nil)

        let name = try await service.fetchPreferredName()

        XCTAssertNil(name)
    }

    func testPropagatesOnboardingErrors() async {
        struct TestError: Error {}
        mockOnboarding.statusError = TestError()

        do {
            _ = try await service.fetchPreferredName()
            XCTFail("expected error to propagate")
        } catch is TestError {
            // expected
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }
}
