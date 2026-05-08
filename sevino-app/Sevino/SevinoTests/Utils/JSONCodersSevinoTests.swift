import XCTest
@testable import Sevino

final class JSONCodersSevinoTests: XCTestCase {

    private struct Sample: Decodable, Equatable {
        let t: Date
        let amount: String
    }

    func test_decoder_decodesIso8601DateField_withZSuffix() throws {
        let json = Data(#"{"t":"2025-12-14T00:00:00Z","amount":"123.45"}"#.utf8)

        let sample = try JSONDecoder.sevino().decode(Sample.self, from: json)

        XCTAssertEqual(sample.t.timeIntervalSince1970, 1765670400, accuracy: 0.001)
        XCTAssertEqual(sample.amount, "123.45")
    }

    func test_decoder_decodesIso8601DateField_withOffsetSuffix() throws {
        // Backend sometimes emits `+00:00` instead of `Z`; both should parse.
        let json = Data(#"{"t":"2025-12-14T00:00:00+00:00","amount":"0"}"#.utf8)

        let sample = try JSONDecoder.sevino().decode(Sample.self, from: json)

        XCTAssertEqual(sample.t.timeIntervalSince1970, 1765670400, accuracy: 0.001)
    }

    func test_decoder_convertsSnakeCaseKeys() throws {
        struct SnakeSample: Decodable { let myField: String }
        let json = Data(#"{"my_field":"value"}"#.utf8)

        let sample = try JSONDecoder.sevino().decode(SnakeSample.self, from: json)

        XCTAssertEqual(sample.myField, "value")
    }

    func test_encoder_convertsToSnakeCase() throws {
        struct EncodeSample: Encodable { let myField: String }

        let data = try JSONEncoder.sevino().encode(EncodeSample(myField: "v"))
        let string = String(data: data, encoding: .utf8) ?? ""

        XCTAssertTrue(string.contains("my_field"))
        XCTAssertFalse(string.contains("myField"))
    }
}
