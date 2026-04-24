import Foundation
import Testing
@testable import Sevino

@Suite("PhoneVerificationViewModel")
struct PhoneVerificationViewModelTests {

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

    @Test("Entering 6th digit auto-triggers confirm")
    func sixthDigitAutoSubmits() async {
        let mock = MockPhoneVerificationService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(mock.confirmedCalls.count == 1)
        #expect(mock.confirmedCalls.first?.code == "123456")
    }

    @Test("Partial OTP does not trigger confirm")
    func partialDoesNotSubmit() async {
        let mock = MockPhoneVerificationService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("12345")
        #expect(mock.confirmedCalls.isEmpty)
    }

    // MARK: - confirm outcomes

    @Test("Successful confirm sets isVerified")
    func confirmSuccessSetsVerified() async {
        let vm = makeVM()
        await vm.updateOTP("123456")
        #expect(vm.isVerified)
        #expect(vm.error == nil)
    }

    @Test("Invalid-code confirm sets error and leaves isVerified false")
    func confirmInvalidCodeSetsError() async {
        let mock = MockPhoneVerificationService()
        mock.confirmOTPError = APIError(error: "Bad code", code: "PHONE_VERIFICATION_FAILED")
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .invalidCode)
        #expect(!vm.isVerified)
    }

    @Test("Network error during confirm maps to .network")
    func confirmNetworkErrorMaps() async {
        let mock = MockPhoneVerificationService()
        mock.confirmOTPError = URLError(.notConnectedToInternet)
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .network)
    }

    @Test("New confirm attempt clears stale error before running")
    func newAttemptClearsStaleError() async {
        let mock = MockPhoneVerificationService()
        mock.confirmOTPError = APIError(error: "Bad code", code: "PHONE_VERIFICATION_FAILED")
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error == .invalidCode)

        mock.confirmOTPError = nil
        await vm.updateOTP("000000")

        #expect(vm.error == nil)
        #expect(vm.isVerified)
    }

    // MARK: - confirmOTP guards

    @Test("confirmOTP is no-op when OTP is incomplete")
    func confirmIncompleteIsNoOp() async {
        let mock = MockPhoneVerificationService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("12345")
        await vm.confirmOTP()
        #expect(mock.confirmedCalls.isEmpty)
    }

    @Test("Auto-submit suppressed once already verified")
    func autoSubmitSuppressedAfterVerify() async {
        let mock = MockPhoneVerificationService()
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.isVerified)

        await vm.updateOTP("000000")
        #expect(mock.confirmedCalls.count == 1)
    }

    // MARK: - onAppear

    @Test("onAppear sends the initial OTP")
    func onAppearSends() async {
        let mock = MockPhoneVerificationService()
        let vm = makeVM(mock: mock)
        await vm.onAppear()
        #expect(mock.sentPhoneNumbers == ["(555) 123-4567"])
    }

    @Test("onAppear is idempotent across repeated calls")
    func onAppearIdempotent() async {
        let mock = MockPhoneVerificationService()
        let vm = makeVM(mock: mock)
        await vm.onAppear()
        await vm.onAppear()
        #expect(mock.sentPhoneNumbers.count == 1)
    }

    @Test("onAppear send failure surfaces a VerificationError")
    func onAppearFailureSetsError() async {
        let mock = MockPhoneVerificationService()
        mock.sendOTPError = URLError(.notConnectedToInternet)
        let vm = makeVM(mock: mock)
        await vm.onAppear()
        #expect(vm.error == .network)
    }

    // MARK: - clearError

    @Test("clearError clears the current error")
    func clearErrorClears() async {
        let mock = MockPhoneVerificationService()
        mock.confirmOTPError = APIError(error: "Bad", code: "PHONE_VERIFICATION_FAILED")
        let vm = makeVM(mock: mock)
        await vm.updateOTP("123456")
        #expect(vm.error != nil)

        vm.clearError()
        #expect(vm.error == nil)
    }

    // MARK: - resend & cooldown

    @Test("Initial send populates secondsRemaining = 30 and !canResend")
    func initialSendStartsCooldown() async {
        let mock = MockPhoneVerificationService()
        let clock = MockClock()
        clock.pauseSleeps = true
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()

        #expect(vm.secondsRemaining == PhoneVerificationViewModel.cooldownSeconds)
        #expect(!vm.canResend)

        vm.cooldownTask?.cancel()
    }

    @Test("Cooldown decrements to 0 over 30 ticks via the clock")
    func cooldownDecrementsToZero() async {
        let mock = MockPhoneVerificationService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()
        await vm.cooldownTask?.value

        #expect(vm.secondsRemaining == 0)
        #expect(clock.sleepCalls == Array(repeating: 1, count: PhoneVerificationViewModel.cooldownSeconds))
    }

    @Test("canResend becomes true once the cooldown completes")
    func canResendTrueAfterCooldown() async {
        let mock = MockPhoneVerificationService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()
        await vm.cooldownTask?.value

        #expect(vm.canResend)
    }

    @Test("Resend during cooldown is a no-op")
    func resendNoOpDuringCooldown() async {
        let mock = MockPhoneVerificationService()
        let clock = MockClock()
        clock.pauseSleeps = true
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()
        await vm.resendOTP()

        #expect(mock.sentPhoneNumbers.count == 1)

        vm.cooldownTask?.cancel()
    }

    @Test("Resend after cooldown calls service and restarts countdown")
    func resendAfterCooldownRestartsCountdown() async {
        let mock = MockPhoneVerificationService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()
        await vm.cooldownTask?.value

        await vm.resendOTP()
        await vm.cooldownTask?.value

        #expect(mock.sentPhoneNumbers.count == 2)
        #expect(clock.sleepCalls.count == PhoneVerificationViewModel.cooldownSeconds * 2)
    }

    @Test("Send failure leaves the cooldown un-started so the user can retry")
    func sendFailureDoesNotStartCooldown() async {
        let mock = MockPhoneVerificationService()
        mock.sendOTPError = URLError(.notConnectedToInternet)
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()

        #expect(vm.secondsRemaining == 0)
        #expect(vm.canResend)
        #expect(clock.sleepCalls.isEmpty)
    }

    @Test("Successful confirm blocks future resends via canResend")
    func verifiedBlocksResend() async {
        let mock = MockPhoneVerificationService()
        let clock = MockClock()
        let vm = makeVM(mock: mock, clock: clock)

        await vm.onAppear()
        await vm.cooldownTask?.value
        await vm.updateOTP("123456")

        #expect(vm.isVerified)
        #expect(!vm.canResend)
    }

    // MARK: - helpers

    private func makeVM(
        mock: MockPhoneVerificationService = MockPhoneVerificationService(),
        clock: any ClockProtocol = MockClock()
    ) -> PhoneVerificationViewModel {
        PhoneVerificationViewModel(
            phoneNumber: "(555) 123-4567",
            service: mock,
            clock: clock
        )
    }
}
