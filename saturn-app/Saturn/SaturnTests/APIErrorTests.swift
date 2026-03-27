import XCTest
@testable import Saturn

final class APIErrorTests: XCTestCase {

    // MARK: - Decoding

    func testDecodesErrorWithAllFields() throws {
        let json = """
        {
            "error": "Validation error",
            "code": "VALIDATION_ERROR",
            "detail": {"fields": [{"field": "body.email", "message": "field required", "type": "value_error.missing"}]}
        }
        """.data(using: .utf8)!

        let error = try JSONDecoder().decode(APIError.self, from: json)

        XCTAssertEqual(error.error, "Validation error")
        XCTAssertEqual(error.code, APIError.Code.validationError)
        XCTAssertNotNil(error.detail)
        XCTAssertNotNil(error.detail?["fields"])
    }

    func testDecodesErrorWithoutDetail() throws {
        let json = """
        {"error": "Not authenticated", "code": "AUTHENTICATION_ERROR"}
        """.data(using: .utf8)!

        let error = try JSONDecoder().decode(APIError.self, from: json)

        XCTAssertEqual(error.error, "Not authenticated")
        XCTAssertEqual(error.code, APIError.Code.authenticationError)
        XCTAssertNil(error.detail)
    }

    func testDecodesErrorWithNestedDetail() throws {
        let json = """
        {
            "error": "Validation error",
            "code": "VALIDATION_ERROR",
            "detail": {
                "fields": [
                    {"field": "body.email", "message": "field required", "type": "value_error.missing"},
                    {"field": "body.name", "message": "too short", "type": "value_error.any_str.min_length"}
                ]
            }
        }
        """.data(using: .utf8)!

        let error = try JSONDecoder().decode(APIError.self, from: json)

        let fields = error.detail?["fields"]?.arrayValue
        XCTAssertNotNil(fields)
        XCTAssertEqual(fields?.count, 2)
    }

    func testDecodingFailsOnNonJSON() {
        let html = "<html>502 Bad Gateway</html>".data(using: .utf8)!
        let error = try? JSONDecoder().decode(APIError.self, from: html)

        XCTAssertNil(error)
    }

    func testDecodingFailsOnWrongJSONShape() {
        let json = """
        {"message": "oops", "status": 500}
        """.data(using: .utf8)!

        let error = try? JSONDecoder().decode(APIError.self, from: json)

        XCTAssertNil(error)
    }

    // MARK: - Convenience checks

    func testAuthenticationErrorIsAuthError() {
        let error = APIError(error: "Not authenticated", code: APIError.Code.authenticationError)

        XCTAssertTrue(error.isAuthError)
        XCTAssertFalse(error.isNotFound)
        XCTAssertFalse(error.isRateLimited)
        XCTAssertFalse(error.isServerError)
        XCTAssertFalse(error.isDuplicate)
        XCTAssertFalse(error.isValidationError)
    }

    func testAuthorizationErrorIsAlsoAuthError() {
        let error = APIError(error: "Not authorized", code: APIError.Code.authorizationError)

        XCTAssertTrue(error.isAuthError)
    }

    func testEachCodeTriggersOnlyItsCheck() {
        let cases: [(String, KeyPath<APIError, Bool>)] = [
            (APIError.Code.notFound, \.isNotFound),
            (APIError.Code.rateLimitExceeded, \.isRateLimited),
            (APIError.Code.internalError, \.isServerError),
            (APIError.Code.duplicateEntry, \.isDuplicate),
            (APIError.Code.validationError, \.isValidationError),
        ]

        for (code, expectedPath) in cases {
            let error = APIError(error: "test", code: code)
            XCTAssertTrue(error[keyPath: expectedPath], "\(code) should trigger its check")
        }
    }

    func testUnknownCodeTriggersNoChecks() {
        let error = APIError(error: "Something new", code: "ACCOUNT_SUSPENDED")

        XCTAssertFalse(error.isAuthError)
        XCTAssertFalse(error.isNotFound)
        XCTAssertFalse(error.isRateLimited)
        XCTAssertFalse(error.isServerError)
        XCTAssertFalse(error.isDuplicate)
        XCTAssertFalse(error.isValidationError)
        XCTAssertEqual(error.code, "ACCOUNT_SUSPENDED")
    }

    // MARK: - Equatable

    func testEqualWhenSameErrorAndCode() {
        let a = APIError(error: "Not found", code: APIError.Code.notFound)
        let b = APIError(error: "Not found", code: APIError.Code.notFound)

        XCTAssertEqual(a, b)
    }

    func testNotEqualWhenDifferentCode() {
        let a = APIError(error: "Something", code: APIError.Code.notFound)
        let b = APIError(error: "Something", code: APIError.Code.conflict)

        XCTAssertNotEqual(a, b)
    }

    func testEqualIgnoresDetail() {
        let a = APIError(error: "Validation error", code: APIError.Code.validationError, detail: ["field": AnyCodable("email")])
        let b = APIError(error: "Validation error", code: APIError.Code.validationError)

        XCTAssertEqual(a, b)
    }

    // MARK: - LocalizedError

    func testLocalizedDescriptionReturnsErrorMessage() {
        let error = APIError(error: "That email is already taken", code: APIError.Code.duplicateEntry)

        XCTAssertEqual(error.localizedDescription, "That email is already taken")
    }

    // MARK: - Fallback

    func testUnknownFallbackHasExpectedValues() {
        XCTAssertEqual(APIError.unknown.error, "Something went wrong")
        XCTAssertEqual(APIError.unknown.code, APIError.Code.unknown)
    }
}
