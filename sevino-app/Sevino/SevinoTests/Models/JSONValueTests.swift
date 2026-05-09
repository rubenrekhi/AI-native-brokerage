import XCTest
@testable import Sevino

final class JSONValueTests: XCTestCase {

    private let decoder = JSONDecoder()

    // MARK: - Primitive variants

    func testDecodesNull() throws {
        let json = Data("null".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .null)
    }

    func testDecodesBoolTrue() throws {
        let json = Data("true".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .bool(true))
    }

    func testDecodesBoolFalse() throws {
        let json = Data("false".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .bool(false))
    }

    func testDecodesString() throws {
        let json = Data("\"hello\"".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .string("hello"))
    }

    // MARK: - Number narrowing (int-before-double ordering)

    func testIntegerDecodesAsIntNotDouble() throws {
        // Pins the documented decode order: a literal that fits Int must
        // surface as `.int`, not `.double` — round-trip equality checks
        // (used in SSEEvent tests) depend on the narrower type winning.
        let json = Data("42".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .int(42))
    }

    func testNegativeIntegerDecodesAsInt() throws {
        let json = Data("-7".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .int(-7))
    }

    func testZeroDecodesAsInt() throws {
        let json = Data("0".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .int(0))
    }

    func testFractionalNumberDecodesAsDouble() throws {
        // Decimal point forces JSONDecoder to refuse Int — falls through to
        // the Double branch.
        let json = Data("3.14".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .double(3.14))
    }

    func testLargeNumberBeyondIntDecodesAsDouble() throws {
        // 1e20 doesn't fit in Int64; must fall through to .double.
        let json = Data("1e20".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        guard case let .double(d) = value else {
            XCTFail("expected .double for 1e20, got \(value)")
            return
        }
        XCTAssertEqual(d, 1e20, accuracy: 1e10)
    }

    // MARK: - Container variants

    func testDecodesEmptyArray() throws {
        let json = Data("[]".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .array([]))
    }

    func testDecodesEmptyObject() throws {
        let json = Data("{}".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .object([:]))
    }

    func testDecodesHeterogeneousArray() throws {
        let json = Data("[1, \"two\", true, null, 3.5]".utf8)
        let value = try decoder.decode(JSONValue.self, from: json)
        XCTAssertEqual(value, .array([
            .int(1),
            .string("two"),
            .bool(true),
            .null,
            .double(3.5),
        ]))
    }

    func testDecodesNestedObject() throws {
        let json = Data("""
        {
            "name": "stock_card",
            "price": 123.45,
            "bars": [{"t": "2026-01-01", "c": 100}],
            "logo": null,
            "live": true
        }
        """.utf8)

        let value = try decoder.decode(JSONValue.self, from: json)

        XCTAssertEqual(value, .object([
            "name": .string("stock_card"),
            "price": .double(123.45),
            "bars": .array([
                .object([
                    "t": .string("2026-01-01"),
                    "c": .int(100),
                ]),
            ]),
            "logo": .null,
            "live": .bool(true),
        ]))
    }

    // MARK: - Failure branches

    func testMalformedJSONThrows() {
        let json = Data("not json".utf8)
        XCTAssertThrowsError(try decoder.decode(JSONValue.self, from: json))
    }

    func testTrailingGarbageAfterValidValueThrows() {
        let json = Data("42 garbage".utf8)
        XCTAssertThrowsError(try decoder.decode(JSONValue.self, from: json))
    }
}
