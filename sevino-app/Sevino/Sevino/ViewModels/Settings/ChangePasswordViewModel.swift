import Foundation

@Observable
final class ChangePasswordViewModel {
    private let authService: AuthServiceProtocol

    var currentPassword = ""
    var newPassword = ""
    var confirmPassword = ""

    private(set) var isLoading = false
    private(set) var error: String?
    private(set) var didSucceed = false

    init(authService: AuthServiceProtocol = AuthService.shared) {
        self.authService = authService
    }

    var passwordsMatch: Bool { newPassword == confirmPassword }

    var meetsRequirements: Bool {
        Self.meetsRequirements(newPassword)
    }

    var isValid: Bool {
        !currentPassword.isEmpty && !newPassword.isEmpty && passwordsMatch && meetsRequirements
    }

    func changePassword() async {
        error = nil
        didSucceed = false

        guard meetsRequirements else {
            error = L10n.Settings.passwordRequirementsError
            return
        }
        guard passwordsMatch else {
            error = L10n.Settings.passwordMismatchError
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            try await authService.updatePassword(
                currentPassword: currentPassword,
                newPassword: newPassword
            )
            didSucceed = true
        } catch let error as PasswordChangeError {
            // PasswordChangeError is LocalizedError — localizedDescription returns a
            // user-facing L10n string for the known cases.
            self.error = error.localizedDescription
        } catch {
            // Unknown error (network, decoding, etc.) — don't leak raw SDK strings.
            self.error = L10n.Settings.changePasswordGenericError
        }
    }

    func clearError() {
        error = nil
    }

    static func meetsRequirements(_ password: String) -> Bool {
        password.contains(where: \.isUppercase) &&
        password.contains(where: \.isLowercase) &&
        password.contains(where: \.isNumber) &&
        (8...64).contains(password.count) &&
        password.contains { !$0.isLetter && !$0.isNumber && !$0.isWhitespace } &&
        !password.contains(" ")
    }
}
