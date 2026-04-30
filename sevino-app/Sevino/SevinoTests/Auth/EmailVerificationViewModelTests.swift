import Auth
import Foundation
import Testing
@testable import Sevino

@Suite("EmailVerificationViewModel")
struct EmailVerificationViewModelTests {

    // MARK: - isOTPComplete

    @Test("Empty OTP is not complete")
    func emptyOTPIsNotComplete() {
        let vm = makeVM()
        #expect(!vm.isOTPComplete)
    }

    @Test("5-digit OTP is not complete")
    func partialOTPIsNotComplete() async {
        let vm = makeVM()
        await vm.updateOTP("12345")
        #expect(!vm.isOTPComplete)
    }

    @Test("6-digit OTP is complete")
    func sixDigitOTPIsComplete() async {
        let vm = makeVM()
        await vm.updateOTP("123456")
        #expect(vm.isOTPComplete)
    }

    // MARK: - updateOTP filtering

    @Test("updateOTP strips non-digit characters")
    func updateOTPStripsNonDigits() async {
        let vm = makeVM()
        await vm.updateOTP("12-3 4 5 6abc")
        #expect(vm.otp == "123456")
    }

    @Test("updateOTP caps at 6 digits")
    func updateOTPCapsAtSix() async {
        let vm = makeVM()
        await vm.updateOTP("12345678")
        #expect(vm.otp == "123456")
    }

    // MARK: - auto-submit on 6th digit

    @Test("Entering 6th digit auto-triggers verify")
    func sixthDigitAutoSubmits() async {
        let mock = MockAuthService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(mock.verifyCallCount == 1)
        #expect(mock.lastVerifiedCode == "123456")
    }

    @Test("Partial OTP does not trigger verify")
    func partialDoesNotSubmit() async {
        let mock = MockAuthService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("12345")
        #expect(mock.verifyCallCount == 0)
    }

    // MARK: - confirm outcomes

    @Test("Successful verify flips isVerified through AuthService")
    func confirmSuccessSetsVerified() async {
        let mock = MockAuthService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.isVerified)
        #expect(vm.error == nil)
    }

    @Test("Invalid-code AuthError maps to .invalidCode")
    func confirmInvalidCodeSetsError() async {
        let mock = MockAuthService()
        mock.errorToThrow = makeAuthError(errorCode: .otpExpired)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .invalidCode)
        #expect(!vm.isVerified)
    }

    @Test("Rate-limit AuthError on verify maps to .tooManyAttempts")
    func confirmRateLimitMaps() async {
        let mock = MockAuthService()
        mock.errorToThrow = makeAuthError(errorCode: .overRequestRateLimit)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .tooManyAttempts)
    }

    @Test("Network error during verify maps to .network")
    func confirmNetworkErrorMaps() async {
        let mock = MockAuthService()
        mock.errorToThrow = URLError(.notConnectedToInternet)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .network)
    }

    @Test("otp_disabled AuthError maps to .sendFailed")
    func confirmOtpDisabledMaps() async {
        let mock = MockAuthService()
        mock.verifyErrorToThrow = makeAuthError(errorCode: .otpDisabled)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .sendFailed)
    }

    @Test("New verify attempt clears stale error before running")
    func newAttemptClearsStaleError() async {
        let mock = MockAuthService()
        mock.errorToThrow = makeAuthError(errorCode: .otpExpired)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .invalidCode)

        mock.errorToThrow = nil
        await vm.updateOTP("000000")

        #expect(vm.error == nil)
        #expect(vm.isVerified)
    }

    @Test("clearError followed by a successful verify leaves no error")
    func clearErrorThenSuccess() async {
        let mock = MockAuthService()
        mock.verifyErrorToThrow = makeAuthError(errorCode: .otpExpired)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .invalidCode)

        vm.clearError()
        mock.verifyErrorToThrow = nil
        await vm.updateOTP("000000")

        #expect(vm.error == nil)
        #expect(vm.isVerified)
    }

    // MARK: - confirmOTP guards

    @Test("confirmOTP is no-op when OTP is incomplete")
    func confirmIncompleteIsNoOp() async {
        let mock = MockAuthService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("12345")
        await vm.confirmOTP()
        #expect(mock.verifyCallCount == 0)
    }

    @Test("Auto-submit suppressed once already verified")
    func autoSubmitSuppressedAfterVerify() async {
        let mock = MockAuthService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.isVerified)

        await vm.updateOTP("000000")
        #expect(mock.verifyCallCount == 1)
    }

    // MARK: - onAppear

    @Test("onAppear does not send OTP — Supabase already dispatched it during signUp")
    func onAppearDoesNotSend() {
        let mock = MockAuthService()
        let vm = makeVM(mock: mock)
        vm.onAppear()
        #expect(mock.resendCallCount == 0)
        #expect(vm.error == nil)
    }

    @Test("onAppear is idempotent across repeated calls (no duplicate cooldown)")
    func onAppearIdempotent() {
        let mock = MockAuthService()
        let clock = MockClock()
        clock.pauseSleeps = true
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        let firstTask = vm.cooldownTask
        vm.onAppear()

        #expect(vm.cooldownTask == firstTask, "second call must not replace the in-flight cooldown")
        #expect(mock.resendCallCount == 0)

        vm.cooldownTask?.cancel()
    }

    // MARK: - clearError

    @Test("clearError clears the current error AND wipes the rejected OTP")
    func clearErrorClears() async {
        let mock = MockAuthService()
        mock.errorToThrow = makeAuthError(errorCode: .otpExpired)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error != nil)

        vm.clearError()
        #expect(vm.error == nil)
        #expect(vm.otp == "", "the rejected code must be wiped so the user can re-enter without manually backspacing six digits")
    }

    @Test("After clearError, retyping the same 6 digits re-runs verify (regression: stale-OTP short-circuit)")
    func clearErrorAllowsRetypingSameCode() async {
        let mock = MockAuthService()
        mock.errorToThrow = makeAuthError(errorCode: .otpExpired)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .invalidCode)
        #expect(mock.verifyCallCount == 1)

        vm.clearError()
        // Mock now succeeds; user retypes the SAME code that was rejected.
        // Without the otp = "" reset in clearError, updateOTP would treat
        // "123456" -> "123456" as a no-op and never re-fire the auto-submit.
        mock.errorToThrow = nil
        await vm.updateOTP("123456")

        #expect(mock.verifyCallCount == 2, "auto-submit must re-fire when the user re-enters the same code after dismissing the error")
        #expect(vm.isVerified)
    }

    // MARK: - resend & cooldown

    @Test("onAppear populates secondsRemaining = 15 and !canResend")
    func initialOnAppearStartsCooldown() {
        let mock = MockAuthService()
        let clock = MockClock()
        clock.pauseSleeps = true
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()

        #expect(vm.secondsRemaining == EmailVerificationViewModel.cooldownSeconds)
        #expect(!vm.canResend)

        vm.cooldownTask?.cancel()
    }

    @Test("Cooldown decrements to 0 over 15 ticks via the clock")
    func cooldownDecrementsToZero() async {
        let mock = MockAuthService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.cooldownTask?.value

        #expect(vm.secondsRemaining == 0)
        #expect(clock.sleepCalls == Array(repeating: 1, count: EmailVerificationViewModel.cooldownSeconds))
    }

    @Test("canResend becomes true once the cooldown completes")
    func canResendTrueAfterCooldown() async {
        let mock = MockAuthService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.cooldownTask?.value

        #expect(vm.canResend)
    }

    @Test("Resend during cooldown is a no-op")
    func resendNoOpDuringCooldown() async {
        let mock = MockAuthService()
        let clock = MockClock()
        clock.pauseSleeps = true
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.resendOTP()

        #expect(mock.resendCallCount == 0, "cooldown blocks the resend before the service is called")

        vm.cooldownTask?.cancel()
    }

    @Test("Resend after cooldown calls service and restarts countdown")
    func resendAfterCooldownRestartsCountdown() async {
        let mock = MockAuthService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.cooldownTask?.value

        await vm.resendOTP()
        await vm.cooldownTask?.value

        #expect(mock.resendCallCount == 1)
        #expect(clock.sleepCalls.count == EmailVerificationViewModel.cooldownSeconds * 2)
    }

    @Test("Resend failure surfaces error and keeps user able to retry")
    func resendFailureSurfacesError() async {
        let mock = MockAuthService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.cooldownTask?.value

        mock.errorToThrow = URLError(.notConnectedToInternet)
        await vm.resendOTP()

        #expect(vm.error == .network)
        #expect(vm.canResend, "no new cooldown started, so user can retry immediately")
    }

    @Test("Resend cooldown error from AuthService maps to .tooManyAttempts")
    func resendCooldownErrorMaps() async {
        let mapped = VerificationError.from(EmailVerificationError.resendCooldown)
        #expect(mapped == .tooManyAttempts)
    }

    @Test("AuthService cooldown firing after VM cooldown elapsed surfaces .tooManyAttempts")
    func authServiceCooldownAfterVmCooldownElapsed() async {
        let mock = MockAuthService()
        mock.emailResendAvailableAt = Date().addingTimeInterval(60)
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.cooldownTask?.value

        await vm.resendOTP()

        #expect(vm.error == .tooManyAttempts)
        #expect(mock.resendCallCount == 0)
    }

    @Test("Successful verify blocks future resends via canResend")
    func verifiedBlocksResend() async {
        let mock = MockAuthService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        vm.onAppear()
        await vm.cooldownTask?.value
        await vm.updateOTP("123456")

        #expect(vm.isVerified)
        #expect(!vm.canResend)
    }

    // MARK: - helpers

    private func makeVM(
        mock: MockAuthService = MockAuthService(),
        clock: any ClockProtocol = MockClock()
    ) -> EmailVerificationViewModel {
        EmailVerificationViewModel(
            email: "test@example.com",
            authService: mock,
            clock: clock
        )
    }

    /// Builds a minimal `AuthError.api` carrying the given `errorCode`. The
    /// underlying response/data are throwaway — only `errorCode` is used by
    /// the mapper under test.
    private func makeAuthError(errorCode: ErrorCode) -> AuthError {
        let response = HTTPURLResponse(
            url: URL(string: "https://example.invalid")!,
            statusCode: 400,
            httpVersion: nil,
            headerFields: nil
        )!
        return .api(
            message: "test error",
            errorCode: errorCode,
            underlyingData: Data(),
            underlyingResponse: response
        )
    }
}
