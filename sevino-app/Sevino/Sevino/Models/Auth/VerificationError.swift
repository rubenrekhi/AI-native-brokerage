import Auth
import Foundation

/**
 User-facing error for the phone- and email-OTP verification flows.

 Maps backend `APIError` codes (phone, via Sevino API), Supabase `AuthError`
 codes (email, direct GoTrue), `EmailVerificationError.resendCooldown` (our
 own client-side cooldown guard), and `URLError` (offline) into a small set
 of cases the UI can render with a clear, localized message. The view model
 raises one of these and the view binds the message directly via
 `errorDescription`.
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
     Convert any thrown error from a verification service into a `VerificationError`.

     Dispatch order:
     1. `APIError` — phone flow, talks to the Sevino API. Mapped on `code`
        (and `detail.code` for GoTrue sub-codes nested inside
        `PHONE_VERIFICATION_FAILED`).
     2. `AuthError` — email flow, talks to Supabase GoTrue directly.
     3. `EmailVerificationError.resendCooldown` — our own client-side guard
        in `AuthService` when `resendEmailConfirmation` is called inside the
        15s cooldown window. Surfaces as "too many attempts".
     4. `URLError` → `.network`.
     5. Anything else → `.unknown`.
     */
    static func from(_ error: Error) -> VerificationError {
        if let apiError = error as? APIError {
            return from(apiError: apiError)
        }
        if let authError = error as? AuthError {
            return from(authError: authError)
        }
        if let emailError = error as? EmailVerificationError {
            return from(emailVerificationError: emailError)
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

    /// Supabase GoTrue conflates "wrong code" and "expired code" under a single
    /// `otp_expired` error code, so a failed verify maps to `.invalidCode` — the
    /// user reaction is the same (try a different code or request a new one) and
    /// the message is more accurate than claiming the code expired.
    ///
    /// Rate-limit codes (`over_request_rate_limit`, `over_email_send_rate_limit`)
    /// surface as `.tooManyAttempts`. `otp_disabled` (server has OTPs turned off)
    /// surfaces as `.sendFailed` so the UI doesn't promise a code that won't
    /// arrive. Anything else falls through to `.unknown`.
    static func from(authError: AuthError) -> VerificationError {
        switch authError.errorCode {
        case .otpExpired:
            return .invalidCode
        case .overEmailSendRateLimit, .overRequestRateLimit:
            return .tooManyAttempts
        case .otpDisabled:
            return .sendFailed
        default:
            return .unknown
        }
    }

    static func from(emailVerificationError: EmailVerificationError) -> VerificationError {
        switch emailVerificationError {
        case .resendCooldown:
            return .tooManyAttempts
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
