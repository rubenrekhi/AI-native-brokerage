import XCTest
@testable import Sevino

@MainActor
final class DecimalStringTests: XCTestCase {

    private struct Sample: Codable, Equatable {
        @DecimalString var amount: Decimal
    }

    // MARK: - Decode

    func testDecode_positive_preservesValue() throws {
        let json = #"{"amount":"1084.92"}"#.data(using: .utf8)!
        let sample = try JSONDecoder().decode(Sample.self, from: json)
        XCTAssertEqual(sample.amount, Decimal(string: "1084.92"))
    }

    func testDecode_negative_preservesSign() throws {
        let json = #"{"amount":"-1049.32"}"#.data(using: .utf8)!
        let sample = try JSONDecoder().decode(Sample.self, from: json)
        XCTAssertEqual(sample.amount, Decimal(string: "-1049.32"))
    }

    func testDecode_trailingZeros_normalizesToDecimalValue() throws {
        let json = #"{"amount":"0.125000000"}"#.data(using: .utf8)!
        let sample = try JSONDecoder().decode(Sample.self, from: json)
        XCTAssertEqual(sample.amount, Decimal(string: "0.125"))
    }

    func testDecode_nonNumericString_throwsDecodingError() {
        let json = #"{"amount":"foo"}"#.data(using: .utf8)!
        XCTAssertThrowsError(try JSONDecoder().decode(Sample.self, from: json)) { error in
            guard case DecodingError.dataCorrupted = error else {
                return XCTFail("Expected DecodingError.dataCorrupted, got \(error)")
            }
        }
    }

    // MARK: - Encode

    func testEncode_producesJSONString() throws {
        let sample = Sample(amount: Decimal(string: "1084.92")!)
        let data = try JSONEncoder().encode(sample)
        let json = String(data: data, encoding: .utf8)
        XCTAssertEqual(json, #"{"amount":"1084.92"}"#)
    }

    // MARK: - Round-trip

    func testRoundTrip_preservesExactString() throws {
        let original = #"{"amount":"1084.92"}"#.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(Sample.self, from: original)
        let encoded = try JSONEncoder().encode(decoded)
        XCTAssertEqual(String(data: encoded, encoding: .utf8), #"{"amount":"1084.92"}"#)
    }
}
