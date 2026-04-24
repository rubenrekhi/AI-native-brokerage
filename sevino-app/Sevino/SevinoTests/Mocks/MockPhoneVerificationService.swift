import Foundation
@testable import Sevino

final class MockPhoneVerificationService: PhoneVerificationServiceProtocol, @unchecked Sendable {
    var sendOTPError: Error?
    var confirmOTPError: Error?

    private(set) var sentPhoneNumbers: [String] = []
    private(set) var confirmedCalls: [(phoneNumber: String, code: String)] = []

    func sendOTP(phoneNumber: String) async throws {
        sentPhoneNumbers.append(phoneNumber)
        if let error = sendOTPError { throw error }
    }

    func confirmOTP(phoneNumber: String, code: String) async throws {
        confirmedCalls.append((phoneNumber, code))
        if let error = confirmOTPError { throw error }
    }
}
