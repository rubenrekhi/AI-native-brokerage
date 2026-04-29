import Foundation
import Testing
@testable import Sevino

@Suite("PhoneVerificationService")
struct PhoneVerificationServiceTests {

    // MARK: - sendOTP

    @Test("sendOTP posts to the verification endpoint")
    func sendOTPCallsCorrectPath() async throws {
        let mock = MockAPIClient()
        let service = PhoneVerificationService(api: mock)

        try await service.sendOTP(phoneNumber: "(555) 123-4567")

        #expect(mock.lastPath == "/v1/auth/phone/send-verification")
        #expect(mock.lastMethod == "POST")
    }

    @Test("sendOTP body normalizes phone number to E.164")
    func sendOTPBodyIsE164() async throws {
        let mock = MockAPIClient()
        let service = PhoneVerificationService(api: mock)

        try await service.sendOTP(phoneNumber: "(555) 123-4567")

        let body = mock.lastBody as? PhoneSendVerificationRequest
        #expect(body == PhoneSendVerificationRequest(phoneNumber: "+15551234567"))
    }

    @Test("sendOTP body encodes phone_number in snake_case on the wire")
    func sendOTPWireFormatIsSnakeCase() async throws {
        let mock = MockAPIClient()
        let service = PhoneVerificationService(api: mock)

        try await service.sendOTP(phoneNumber: "(555) 123-4567")

        let body = try #require(mock.lastBody as? PhoneSendVerificationRequest)
        let json = try wireFormat(body)
        #expect(json["phone_number"] as? String == "+15551234567")
    }

    @Test("sendOTP propagates APIError")
    func sendOTPPropagatesAPIError() async {
        let mock = MockAPIClient()
        mock.errorToThrow = APIError(error: "Slow down", code: APIError.Code.rateLimitExceeded)
        let service = PhoneVerificationService(api: mock)

        await #expect(throws: APIError.self) {
            try await service.sendOTP(phoneNumber: "(555) 123-4567")
        }
    }

    @Test("sendOTP propagates URLError")
    func sendOTPPropagatesURLError() async {
        let mock = MockAPIClient()
        mock.errorToThrow = URLError(.notConnectedToInternet)
        let service = PhoneVerificationService(api: mock)

        await #expect(throws: URLError.self) {
            try await service.sendOTP(phoneNumber: "(555) 123-4567")
        }
    }

    // MARK: - confirmOTP

    @Test("confirmOTP posts to the confirm endpoint")
    func confirmOTPCallsCorrectPath() async throws {
        let mock = MockAPIClient()
        let service = PhoneVerificationService(api: mock)

        try await service.confirmOTP(phoneNumber: "(555) 123-4567", code: "123456")

        #expect(mock.lastPath == "/v1/auth/phone/confirm")
        #expect(mock.lastMethod == "POST")
    }

    @Test("confirmOTP body contains E.164 phone and 6-digit code")
    func confirmOTPBodyShape() async throws {
        let mock = MockAPIClient()
        let service = PhoneVerificationService(api: mock)

        try await service.confirmOTP(phoneNumber: "(555) 123-4567", code: "123456")

        let body = mock.lastBody as? PhoneConfirmVerificationRequest
        #expect(
            body
                == PhoneConfirmVerificationRequest(phoneNumber: "+15551234567", code: "123456")
        )
    }

    @Test("confirmOTP propagates APIError")
    func confirmOTPPropagatesAPIError() async {
        let mock = MockAPIClient()
        mock.errorToThrow = APIError(error: "Bad code", code: "PHONE_VERIFICATION_FAILED")
        let service = PhoneVerificationService(api: mock)

        await #expect(throws: APIError.self) {
            try await service.confirmOTP(phoneNumber: "(555) 123-4567", code: "999999")
        }
    }

    // MARK: - toE164

    @Test("Already-E.164 input passes through")
    func toE164PassesThroughExistingE164() {
        #expect(PhoneVerificationService.toE164("+15551234567") == "+15551234567")
    }

    @Test("10-digit raw input gets +1 prefix")
    func toE164PrefixesTenDigits() {
        #expect(PhoneVerificationService.toE164("5551234567") == "+15551234567")
    }

    @Test("Formatted input is normalized")
    func toE164StripsFormatting() {
        #expect(PhoneVerificationService.toE164("(555) 123-4567") == "+15551234567")
        #expect(PhoneVerificationService.toE164("555-123-4567") == "+15551234567")
        #expect(PhoneVerificationService.toE164("555 123 4567") == "+15551234567")
    }

    @Test("11-digit input starting with 1 gets + prefix only")
    func toE164PrefixesElevenDigitsStartingWithOne() {
        #expect(PhoneVerificationService.toE164("15551234567") == "+15551234567")
    }

    @Test("Malformed input passes through unchanged for backend rejection")
    func toE164DoesNotMangleMalformedInput() {
        #expect(PhoneVerificationService.toE164("123") == "123")
        #expect(PhoneVerificationService.toE164("") == "")
    }

    // MARK: - helpers

    /// Encode a body via the same key strategy `APIClient` uses (snake_case)
    /// and decode it back into a dictionary for wire-shape assertions.
    private func wireFormat(_ body: some Encodable) throws -> [String: Any] {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(body)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return json ?? [:]
    }
}
