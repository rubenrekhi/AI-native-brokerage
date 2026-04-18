import XCTest
@testable import Sevino

final class AnyCodableTests: XCTestCase {

    func testDecodesPrimitiveTypes() throws {
        let json = """
        {
            "string": "hello",
            "int": 42,
            "double": 3.14,
            "bool": true,
            "null": null
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode([String: AnyCodable].self, from: json)

        XCTAssertEqual(decoded["string"]?.stringValue, "hello")
        XCTAssertEqual(decoded["int"]?.intValue, 42)
        XCTAssertEqual(decoded["double"]?.doubleValue, 3.14)
        XCTAssertEqual(decoded["bool"]?.boolValue, true)
        XCTAssertNil(decoded["null"]?.value)
    }

    func testDecodesArray() throws {
        let json = """
        {"items": [1, 2, 3]}
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode([String: AnyCodable].self, from: json)

        let items = decoded["items"]?.arrayValue
        XCTAssertNotNil(items)
        XCTAssertEqual(items?.count, 3)
    }

    func testDecodesNestedObjects() throws {
        let json = """
        {"outer": {"inner": "value"}}
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode([String: AnyCodable].self, from: json)

        let outer = decoded["outer"]?.dictValue
        XCTAssertNotNil(outer)
        XCTAssertEqual(outer?["inner"] as? String, "value")
    }
}
