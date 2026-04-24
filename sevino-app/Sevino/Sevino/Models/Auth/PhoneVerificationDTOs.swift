import Foundation

/// Request body for `/v1/auth/phone/send-verification`. Backend's
/// `PhoneStr` schema only accepts E.164 (`/^\+1\d{10}$/`).
struct PhoneSendVerificationRequest: Encodable, Equatable {
    let phoneNumber: String
}

/// Request body for `/v1/auth/phone/confirm`.
struct PhoneConfirmVerificationRequest: Encodable, Equatable {
    let phoneNumber: String
    let code: String
}
