import Foundation
import Observation
@testable import Sevino

@Observable
final class MockAuthService: AuthServiceProtocol {
    var isAuthenticated = false
    var isEmailVerified = false
    var emailResendAvailableAt: Date?
    var accessToken: String?
    var currentEmail: String?
    /// Default fallback for any method that doesn't have a method-specific
    /// error set. Method-specific fields take precedence so tests can drive
    /// distinct outcomes for verify vs. resend on the same mock instance.
    var errorToThrow: Error?
    var signOutError: Error?
    var resendErrorToThrow: Error?
    var verifyErrorToThrow: Error?
    private(set) var signOutCalls = 0
    private(set) var resendCallCount = 0
    private(set) var verifyCallCount = 0
    private(set) var lastVerifiedCode: String?

    var canResendEmailConfirmation: Bool {
        guard let availableAt = emailResendAvailableAt else { return true }
        return Date() >= availableAt
    }

    func signUp(email: String, password: String) async throws {
        if let error = errorToThrow { throw error }
    }

    func signIn(email: String, password: String) async throws {
        if let error = errorToThrow { throw error }
        isAuthenticated = true
    }

    func signOut() async throws {
        signOutCalls += 1
        if let error = signOutError ?? errorToThrow { throw error }
        isAuthenticated = false
        isEmailVerified = false
    }

    /// Order: cooldown gate (matches AuthService) → bump call counter (so failed
    /// attempts still count toward `resendCallCount`, mirroring
    /// `MockPhoneVerificationService.confirmedCalls`) → method-specific error →
    /// generic `errorToThrow` → success. Tests asserting "errorToThrow runs
    /// while cooldown is active" must clear `emailResendAvailableAt` first.
    func resendEmailConfirmation(email: String) async throws {
        guard canResendEmailConfirmation else {
            throw EmailVerificationError.resendCooldown
        }
        resendCallCount += 1
        if let error = resendErrorToThrow ?? errorToThrow { throw error }
        emailResendAvailableAt = Date().addingTimeInterval(15)
    }

    func verifyEmailConfirmation(email: String, code: String) async throws {
        verifyCallCount += 1
        lastVerifiedCode = code
        if let error = verifyErrorToThrow ?? errorToThrow { throw error }
        isEmailVerified = true
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
