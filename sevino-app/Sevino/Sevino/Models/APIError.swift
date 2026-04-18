import Foundation

/**
 Structured error returned by the Sevino API.
 Every non-2xx response is decoded into this model. Use `code` to drive
 app logic (e.g., redirect to login, highlight a form field) and `error`
 as the user-facing message.
 */

struct APIError: Decodable, Error, Equatable {
    let error: String
    let code: String
    let detail: [String: AnyCodable]?

    init(error: String, code: String, detail: [String: AnyCodable]? = nil) {
        self.error = error
        self.code = code
        self.detail = detail
    }
}

// Equatable (detail excluded — AnyCodable wraps Any? which can't be compared)
extension APIError {
    static func == (lhs: APIError, rhs: APIError) -> Bool {
        lhs.error == rhs.error && lhs.code == rhs.code
    }
}

// Known backend error codes
extension APIError {
    enum Code {
        static let authenticationError = "AUTHENTICATION_ERROR"
        static let authorizationError = "AUTHORIZATION_ERROR"
        static let validationError = "VALIDATION_ERROR"
        static let notFound = "NOT_FOUND"
        static let duplicateEntry = "DUPLICATE_ENTRY"
        static let conflict = "CONFLICT"
        static let rateLimitExceeded = "RATE_LIMIT_EXCEEDED"
        static let internalError = "INTERNAL_ERROR"
        static let invalidData = "INVALID_DATA"
        static let httpError = "HTTP_ERROR"
        static let forbidden = "FORBIDDEN"
        static let incompleteOnboarding = "INCOMPLETE_ONBOARDING"
        static let alpacaError = "ALPACA_ERROR"
        static let alpacaUnavailable = "ALPACA_UNAVAILABLE"
        static let unknown = "UNKNOWN"
    }
}

// Quick checks against common error codes
extension APIError {
    var isAuthError: Bool { code == Code.authenticationError || code == Code.authorizationError }
    var isRateLimited: Bool { code == Code.rateLimitExceeded }
    var isNotFound: Bool { code == Code.notFound }
    var isServerError: Bool { code == Code.internalError }
    var isDuplicate: Bool { code == Code.duplicateEntry }
    var isValidationError: Bool { code == Code.validationError }
}

// Makes error.localizedDescription return our backend message instead of
// Swift's generic "The operation couldn't be completed."
extension APIError: LocalizedError {
    var errorDescription: String? { error }
}

// Fallback when the backend response can't be decoded
extension APIError {
    static let unknown = APIError(
        error: "Something went wrong",
        code: Code.unknown
    )
}
