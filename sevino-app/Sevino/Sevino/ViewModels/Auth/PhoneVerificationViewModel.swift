import Foundation

/// View-model for the phone OTP entry screen.
///
/// Lifecycle:
/// 1. View calls `onAppear()` once on appearance — sends the initial OTP via the
///    service. Subsequent calls are no-ops, so SwiftUI re-renders that re-trigger
///    `.task` don't spam the backend. Resending is opted into via PR-4's resend flow.
/// 2. The view drives `updateOTP(_:)` from the OTP TextField; the VM strips non-digits,
///    caps at 6, and auto-confirms when the 6th digit lands.
/// 3. On a successful confirm `isVerified` becomes `true`; the view observes it to
///    advance the route.
@Observable
final class PhoneVerificationViewModel {
    private let service: any PhoneVerificationServiceProtocol

    /// Formatted phone number shown in the title (e.g. `"(555) 123-4567"`).
    /// Immutable for the lifetime of the screen — to change the number the user pops
    /// back to `PhoneNumberView`.
    let phoneNumber: String

    private(set) var otp: String = ""
    private(set) var isSending: Bool = false
    private(set) var isConfirming: Bool = false
    private(set) var error: VerificationError?
    private(set) var isVerified: Bool = false

    @ObservationIgnored
    private var didSendInitialOTP: Bool = false

    var isOTPComplete: Bool { otp.count == 6 }

    init(
        phoneNumber: String,
        service: any PhoneVerificationServiceProtocol = PhoneVerificationService.shared
    ) {
        self.phoneNumber = phoneNumber
        self.service = service
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

    func clearError() {
        error = nil
    }

    private func sendOTP() async {
        isSending = true
        error = nil
        defer { isSending = false }
        do {
            try await service.sendOTP(phoneNumber: phoneNumber)
        } catch {
            self.error = VerificationError.from(error)
        }
    }
}
