import Foundation

/**
 User-facing error for the phone-OTP verification flow.

 Maps backend `APIError` codes (and `URLError` for offline cases) into a
 small set of cases the UI can render with a clear, localized message.
 The view model raises one of these and the view binds the message
 directly via `errorDescription`.
 */
enum VerificationError: LocalizedError, Equatable {
    case invalidCode
    case expired
    case tooManyAttempts
    case network
    case sendFailed
    case unknown

    var errorDescription: String? {
        switch self {
        case .invalidCode: L10n.Auth.otpInvalidCode
        case .expired: L10n.Auth.otpExpired
        case .tooManyAttempts: L10n.Auth.otpTooManyAttempts
        case .network: L10n.Auth.otpNetworkError
        case .sendFailed: L10n.Auth.otpSendFailed
        case .unknown: L10n.Auth.otpUnknownError
        }
    }
}

extension VerificationError {
    /**
     Convert any thrown error from the verification service into a
     `VerificationError`.

     - `APIError` is dispatched on `code` (and `detail.code` for GoTrue
        error sub-codes nested inside `PHONE_VERIFICATION_FAILED`).
     - `URLError` becomes `.network`.
     - Anything else falls through to `.unknown`.
     */
    static func from(_ error: Error) -> VerificationError {
        if let apiError = error as? APIError {
            return from(apiError: apiError)
        }
        if error is URLError {
            return .network
        }
        return .unknown
    }

    static func from(apiError: APIError) -> VerificationError {
        switch apiError.code {
        case APIError.Code.rateLimitExceeded:
            return .tooManyAttempts
        case Backend.phoneVerificationUnavailable:
            return .sendFailed
        case Backend.phoneVerificationFailed:
            return goTrueDetailCode(apiError) == GoTrue.otpExpired ? .expired : .invalidCode
        default:
            return .unknown
        }
    }

    private static func goTrueDetailCode(_ apiError: APIError) -> String? {
        apiError.detail?["code"]?.stringValue
    }

    private enum Backend {
        static let phoneVerificationFailed = "PHONE_VERIFICATION_FAILED"
        static let phoneVerificationUnavailable = "PHONE_VERIFICATION_UNAVAILABLE"
    }

    private enum GoTrue {
        static let otpExpired = "otp_expired"
    }
}
