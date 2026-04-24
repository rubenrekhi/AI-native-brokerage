import Foundation

/// View-model for the phone OTP entry screen.
///
/// Lifecycle:
/// 1. View calls `onAppear()` once on appearance — sends the initial OTP via the
///    service and starts the resend cooldown. Subsequent calls are no-ops, so
///    SwiftUI re-renders that re-trigger `.task` don't spam the backend.
/// 2. The view drives `updateOTP(_:)` from the OTP TextField; the VM strips non-digits,
///    caps at 6, and auto-confirms when the 6th digit lands.
/// 3. On a successful confirm `isVerified` becomes `true`; the view observes it to
///    advance the route.
/// 4. If the user wants a new code, they tap "Resend" — gated by `canResend` which
///    flips to `true` only after the cooldown counts down to zero.
@Observable
final class PhoneVerificationViewModel {
    static let cooldownSeconds: Int = 30

    private let service: any PhoneVerificationServiceProtocol
    private let clock: any ClockProtocol

    /// Formatted phone number shown in the title (e.g. `"(555) 123-4567"`).
    /// Immutable for the lifetime of the screen — to change the number the user pops
    /// back to `PhoneNumberView`.
    let phoneNumber: String

    private(set) var otp: String = ""
    private(set) var isSending: Bool = false
    private(set) var isConfirming: Bool = false
    private(set) var error: VerificationError?
    private(set) var isVerified: Bool = false
    private(set) var secondsRemaining: Int = 0

    @ObservationIgnored
    private var didSendInitialOTP: Bool = false

    /// Drives the cooldown countdown. Exposed so tests can `await` its completion
    /// to drain the loop deterministically; the view observes `secondsRemaining`
    /// instead of touching the task directly.
    @ObservationIgnored
    private(set) var cooldownTask: Task<Void, Never>?

    var isOTPComplete: Bool { otp.count == 6 }

    var canResend: Bool {
        secondsRemaining == 0 && !isSending && !isConfirming && !isVerified
    }

    init(
        phoneNumber: String,
        service: any PhoneVerificationServiceProtocol = PhoneVerificationService.shared,
        clock: any ClockProtocol = SystemClock()
    ) {
        self.phoneNumber = phoneNumber
        self.service = service
        self.clock = clock
    }

    func onAppear() async {
        guard !didSendInitialOTP else { return }
        didSendInitialOTP = true
        await sendOTP()
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
            try await service.confirmOTP(phoneNumber: phoneNumber, code: otp)
            isVerified = true
        } catch {
            self.error = VerificationError.from(error)
        }
    }

    func resendOTP() async {
        guard canResend else { return }
        await sendOTP()
    }

    func clearError() {
        error = nil
    }

    private func sendOTP() async {
        isSending = true
        error = nil
        defer { isSending = false }
        do {
            try await service.sendOTP(phoneNumber: phoneNumber)
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
