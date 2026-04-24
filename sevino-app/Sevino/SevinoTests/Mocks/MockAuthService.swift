import Observation
@testable import Sevino

@Observable
final class MockAuthService: AuthServiceProtocol {
    var isAuthenticated = false
    var accessToken: String?
    var errorToThrow: Error?

    func signUp(email: String, password: String) async throws {
        if let error = errorToThrow { throw error }
    }

    func signIn(email: String, password: String) async throws {
        if let error = errorToThrow { throw error }
        isAuthenticated = true
    }

    func signOut() async throws {
        if let error = errorToThrow { throw error }
        isAuthenticated = false
    }

    private(set) var updatePasswordCallCount = 0
    private(set) var lastCurrentPassword: String?
    private(set) var lastUpdatedPassword: String?

    func updatePassword(currentPassword: String, newPassword: String) async throws {
        updatePasswordCallCount += 1
        lastCurrentPassword = currentPassword
        lastUpdatedPassword = newPassword
        if let error = errorToThrow { throw error }
    }
}
