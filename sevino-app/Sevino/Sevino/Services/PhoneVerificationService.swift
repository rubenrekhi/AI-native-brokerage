import Foundation

/// Protocol for the phone OTP backend communication — enables mocking in tests and ViewModels.
protocol PhoneVerificationServiceProtocol: Sendable {
    func sendOTP(phoneNumber: String) async throws
    func confirmOTP(phoneNumber: String, code: String) async throws
}

/// Sends and confirms SMS OTP codes against the Sevino API's
/// `/v1/auth/phone/*` endpoints (which proxy Supabase GoTrue + Twilio Verify).
///
/// Inputs accept the formatted phone number used by the UI (`(555) 123-4567`)
/// — `toE164` normalizes it before posting, since the backend's
/// `PhoneStr` schema only accepts `+1`-prefixed E.164 strings.
final class PhoneVerificationService: PhoneVerificationServiceProtocol {
    static let shared = PhoneVerificationService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func sendOTP(phoneNumber: String) async throws {
        let body = PhoneSendVerificationRequest(phoneNumber: Self.toE164(phoneNumber))
        try await api.post("/v1/auth/phone/send-verification", body: body)
    }

    func confirmOTP(phoneNumber: String, code: String) async throws {
        let body = PhoneConfirmVerificationRequest(
            phoneNumber: Self.toE164(phoneNumber),
            code: code
        )
        try await api.post("/v1/auth/phone/confirm", body: body)
    }

    /// Normalize a US phone number into E.164 (`+15551234567`).
    ///
    /// - Already-E.164 inputs (anything starting with `+`) pass through.
    /// - Strips formatting (parens, spaces, dashes) and prefixes `+1` when
    ///   exactly 10 digits remain.
    /// - 11-digit inputs starting with `1` are treated as `+1<10 digits>`.
    /// - Anything else returns unchanged and is rejected by the backend's
    ///   regex validator (`^\+1\d{10}$`) — surfaced as a 422.
    static func toE164(_ phoneNumber: String) -> String {
        if phoneNumber.hasPrefix("+") { return phoneNumber }
        let digits = phoneNumber.filter(\.isNumber)
        if digits.count == 10 { return "+1\(digits)" }
        if digits.count == 11, digits.hasPrefix("1") { return "+\(digits)" }
        return phoneNumber
    }
}
