import Foundation

/// View-model for the email OTP entry screen.
///
/// Lifecycle:
/// 1. The user lands here after a fresh signup. Supabase auto-sends the
///    confirmation OTP as a side-effect of `signUp`, so this screen never
///    dispatches the initial code — `onAppear()` only primes the resend
///    cooldown.
/// 2. The view drives `updateOTP(_:)` from the OTP TextField; the VM strips
///    non-digits, caps at 6, and auto-confirms when the 6th digit lands.
/// 3. On a successful verify Supabase fires a `userUpdated` event and
///    `AuthService.isEmailVerified` flips reactively. `isVerified` is a
///    computed property reading that flag, so the view's `onChange(of:)`
///    on `vm.isVerified` advances the route.
/// 4. If the user wants a new code, they tap "Resend" — gated by `canResend`
///    which only returns true after the 15s cooldown has counted down.
@Observable
final class EmailVerificationViewModel {
    static let cooldownSeconds: Int = 15

    private let authService: any AuthServiceProtocol
    private let clock: any ClockProtocol

    /// The email shown in the title and used for verify/resend calls. Immutable
    /// for the lifetime of the screen — to change the email the user pops back
    /// out of the flow, since Supabase has already created the account.
    let email: String

    private(set) var otp: String = ""
    private(set) var isSending: Bool = false
    private(set) var isConfirming: Bool = false
    private(set) var error: VerificationError?
    private(set) var secondsRemaining: Int = 0

    @ObservationIgnored
    private var didStartCooldown: Bool = false

    /// Drives the cooldown countdown. Exposed so tests can `await` its completion
    /// to drain the loop deterministically; the view observes `secondsRemaining`
    /// instead of touching the task directly.
    @ObservationIgnored
    private(set) var cooldownTask: Task<Void, Never>?

    var isOTPComplete: Bool { otp.count == 6 }

    /// Reactive — derived from `AuthService.isEmailVerified`, which the Supabase
    /// `userUpdated` listener flips. Requires `AuthServiceProtocol` conformers
    /// to be `@Observable` for SwiftUI to re-evaluate downstream `onChange(of:)`
    /// hooks; both `AuthService` and `MockAuthService` already are.
    var isVerified: Bool { authService.isEmailVerified }

    var canResend: Bool {
        secondsRemaining == 0 && !isSending && !isConfirming && !isVerified
    }

    init(
        email: String,
        authService: any AuthServiceProtocol = AuthService.shared,
        clock: any ClockProtocol = SystemClock()
    ) {
        self.email = email
        self.authService = authService
        self.clock = clock
    }

    /// Starts the resend cooldown on first call. Idempotent across SwiftUI
    /// `.task` re-runs. The OTP itself was already dispatched by Supabase
    /// during `signUp`, so this method intentionally does no network.
    func onAppear() {
        guard !didStartCooldown else { return }
        didStartCooldown = true
        startCooldown()
    }

    func updateOTP(_ newValue: String) async {
        let digits = String(newValue.filter(\.isNumber).prefix(6))
        guard otp != digits else { return }
        otp = digits
        if otp.count == 6, !isConfirming, !isVerified {
            await confirmOTP()
        }
    }

    func confirmOTP() async {
        guard !isConfirming, !isVerified, isOTPComplete else { return }
        isConfirming = true
        error = nil
        defer { isConfirming = false }
        do {
            try await authService.verifyEmailConfirmation(email: email, code: otp)
        } catch {
            self.error = VerificationError.from(error)
        }
    }

    func resendOTP() async {
        guard canResend else { return }
        await sendOTP()
    }

    /// Clear the error AND wipe the entered OTP. The user has just acknowledged
    /// a rejected code, so the boxes should reset to empty — otherwise the
    /// digit-equality short-circuit in `updateOTP` would suppress the auto-submit
    /// when they re-type the same length, forcing a manual six-character backspace.
    func clearError() {
        error = nil
        otp = ""
    }

    private func sendOTP() async {
        isSending = true
        error = nil
        defer { isSending = false }
        do {
            try await authService.resendEmailConfirmation(email: email)
            startCooldown()
        } catch {
            self.error = VerificationError.from(error)
        }
    }

    private func startCooldown() {
        cooldownTask?.cancel()
        secondsRemaining = Self.cooldownSeconds
        cooldownTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled, self.secondsRemaining > 0 {
                do {
                    try await self.clock.sleep(seconds: 1)
                } catch {
                    return
                }
                self.secondsRemaining -= 1
            }
        }
    }
}
