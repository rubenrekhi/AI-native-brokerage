import Foundation
@testable import Sevino

final class MockUserProfileService: UserProfileServiceProtocol {
    var fetchPreferredNameError: Error?
    var preferredName: String?

    private(set) var fetchPreferredNameCallCount = 0

    func fetchPreferredName() async throws -> String? {
        fetchPreferredNameCallCount += 1
        if let error = fetchPreferredNameError { throw error }
        return preferredName
    }
}
