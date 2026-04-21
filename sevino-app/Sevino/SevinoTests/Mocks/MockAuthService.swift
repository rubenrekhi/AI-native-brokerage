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
}
