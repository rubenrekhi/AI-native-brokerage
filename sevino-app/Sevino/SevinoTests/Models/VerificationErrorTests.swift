import Foundation
import Testing
@testable import Sevino

@Suite("VerificationError")
struct VerificationErrorTests {

    // MARK: - errorDescription

    @Test("Each case has a non-empty localized description")
    func eachCaseHasLocalizedDescription() {
        let cases: [VerificationError] = [
            .invalidCode, .expired, .tooManyAttempts, .network, .sendFailed, .unknown,
        ]
        for error in cases {
            #expect(error.errorDescription?.isEmpty == false)
        }
    }

    @Test("Cases map to distinct messages")
    func casesMapToDistinctMessages() {
        let messages = Set(
            [
                VerificationError.invalidCode,
                .expired,
                .tooManyAttempts,
                .network,
                .sendFailed,
                .unknown,
            ].compactMap(\.errorDescription)
        )
        #expect(messages.count == 6)
    }

    // MARK: - APIError mapping

    @Test("Rate limit code maps to .tooManyAttempts")
    func rateLimitMapsToTooManyAttempts() {
        let apiError = APIError(error: "Slow down", code: APIError.Code.rateLimitExceeded)
        #expect(VerificationError.from(apiError: apiError) == .tooManyAttempts)
    }

    @Test("Unavailable code maps to .sendFailed")
    func unavailableMapsToSendFailed() {
        let apiError = APIError(error: "Down", code: "PHONE_VERIFICATION_UNAVAILABLE")
        #expect(VerificationError.from(apiError: apiError) == .sendFailed)
    }

    @Test("Verification failed without detail maps to .invalidCode")
    func failedWithoutDetailMapsToInvalidCode() {
        let apiError = APIError(error: "Bad code", code: "PHONE_VERIFICATION_FAILED")
        #expect(VerificationError.from(apiError: apiError) == .invalidCode)
    }

    @Test("Verification failed with otp_expired detail maps to .expired")
    func failedWithExpiredDetailMapsToExpired() {
        let apiError = APIError(
            error: "Token expired",
            code: "PHONE_VERIFICATION_FAILED",
            detail: ["code": AnyCodable("otp_expired")]
        )
        #expect(VerificationError.from(apiError: apiError) == .expired)
    }

    @Test("Verification failed with non-expired detail still maps to .invalidCode")
    func failedWithOtherDetailMapsToInvalidCode() {
        let apiError = APIError(
            error: "Bad code",
            code: "PHONE_VERIFICATION_FAILED",
            detail: ["code": AnyCodable("invalid_phone")]
        )
        #expect(VerificationError.from(apiError: apiError) == .invalidCode)
    }

    @Test("Unknown backend code maps to .unknown")
    func unknownCodeMapsToUnknown() {
        let apiError = APIError(error: "Surprise", code: "SOMETHING_NEW")
        #expect(VerificationError.from(apiError: apiError) == .unknown)
    }

    // MARK: - generic Error mapping

    @Test("URLError maps to .network")
    func urlErrorMapsToNetwork() {
        let urlError = URLError(.notConnectedToInternet)
        #expect(VerificationError.from(urlError) == .network)
    }

    @Test("APIError dispatched through generic from(_:)")
    func apiErrorThroughGenericMapper() {
        let apiError = APIError(error: "x", code: APIError.Code.rateLimitExceeded)
        #expect(VerificationError.from(apiError) == .tooManyAttempts)
    }

    @Test("Other errors fall through to .unknown")
    func otherErrorsFallThrough() {
        struct Bogus: Error {}
        #expect(VerificationError.from(Bogus()) == .unknown)
    }
}
