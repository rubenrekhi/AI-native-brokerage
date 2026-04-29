import XCTest
@testable import Sevino

final class PortfolioDistributionDataTests: XCTestCase {

    private var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    func testDistributionSegmentColorDecodesSnakeCaseRawValues() throws {
        let json = """
        ["info", "positive", "warning", "avatar_purple", "grey_contrast"]
        """.data(using: .utf8)!

        let colors = try decoder.decode([DistributionSegmentColor].self, from: json)

        XCTAssertEqual(colors, [.info, .positive, .warning, .avatarPurple, .greyContrast])
    }

    func testDistributionSegmentColorEncodesSnakeCaseRawValues() throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys

        let encoded = try encoder.encode([DistributionSegmentColor.avatarPurple, .greyContrast])
        let string = String(data: encoded, encoding: .utf8)

        XCTAssertEqual(string, #"["avatar_purple","grey_contrast"]"#)
    }

    func testDistributionSegmentColorRejectsUnknownValue() {
        let json = #""muted_teal""#.data(using: .utf8)!
        XCTAssertThrowsError(try decoder.decode(DistributionSegmentColor.self, from: json))
    }

    func testPortfolioDistributionDataDecodesMultipleSegments() throws {
        let json = """
        {
            "total_value": 12430.18,
            "currency_code": "USD",
            "segments": [
                {
                    "id": "AAPL",
                    "label": "AAPL",
                    "fraction": 0.45,
                    "amount": 5593.58,
                    "color_token": "info"
                },
                {
                    "id": "cash",
                    "label": "Cash",
                    "fraction": 0.10,
                    "amount": 1243.02,
                    "color_token": "grey_contrast"
                }
            ]
        }
        """.data(using: .utf8)!

        let data = try decoder.decode(PortfolioDistributionData.self, from: json)

        XCTAssertEqual(data.currencyCode, "USD")
        XCTAssertEqual(data.totalValue, Decimal(string: "12430.18"))
        XCTAssertEqual(data.segments.count, 2)
        XCTAssertEqual(data.segments[0].id, "AAPL")
        XCTAssertEqual(data.segments[0].colorToken, .info)
        XCTAssertEqual(data.segments[0].fraction, 0.45)
        XCTAssertEqual(data.segments[0].amount, Decimal(string: "5593.58"))
        XCTAssertEqual(data.segments[1].colorToken, .greyContrast)
    }

    func testPortfolioDistributionDataRoundTrips() throws {
        let original = PortfolioDistributionData(
            totalValue: Decimal(string: "1084.92")!,
            currencyCode: "USD",
            segments: [
                DistributionSegment(
                    id: "cash",
                    label: "Cash",
                    fraction: 1.0,
                    amount: Decimal(string: "1084.92")!,
                    colorToken: .warning
                )
            ]
        )

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(PortfolioDistributionData.self, from: encoded)

        XCTAssertEqual(decoded, original)
    }
}
