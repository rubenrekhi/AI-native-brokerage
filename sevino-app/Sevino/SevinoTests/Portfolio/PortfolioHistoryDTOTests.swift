import XCTest
@testable import Sevino

@MainActor
final class PortfolioHistoryDTOTests: XCTestCase {

    private func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .iso8601
        return d
    }

    func test_decodesHistoryWithTwoPoints() throws {
        let json = #"""
        {
          "range": "1M",
          "timeframe": "1D",
          "currency": "USD",
          "base_value": "1000.00",
          "end_value": "1290.00",
          "gain_abs": "290.00",
          "gain_pct": "0.2900",
          "points": [
            { "t": "2025-11-14T00:00:00Z", "v": "1000.00" },
            { "t": "2025-12-14T00:00:00Z", "v": "1290.00" }
          ]
        }
        """#
        let dto = try makeDecoder().decode(PortfolioHistoryDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.range, "1M")
        XCTAssertEqual(dto.timeframe, "1D")
        XCTAssertEqual(dto.baseValue, Decimal(string: "1000.00"))
        XCTAssertEqual(dto.endValue, Decimal(string: "1290.00"))
        XCTAssertEqual(dto.points.count, 2)
        XCTAssertEqual(dto.points[0].v, Decimal(string: "1000.00"))
        XCTAssertEqual(dto.points[1].v, Decimal(string: "1290.00"))
    }

    func test_decodesEmptyPoints() throws {
        let json = #"""
        {
          "range": "1D",
          "timeframe": "5Min",
          "currency": "USD",
          "base_value": "0",
          "end_value": "0",
          "gain_abs": "0",
          "gain_pct": "0",
          "points": []
        }
        """#
        let dto = try makeDecoder().decode(PortfolioHistoryDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.points, [])
        XCTAssertEqual(dto.baseValue, Decimal(0))
    }

    func test_decodesIso8601WithZSuffix() throws {
        let json = #"""
        { "t": "2025-12-14T00:00:00Z", "v": "1000.00" }
        """#
        let point = try makeDecoder().decode(PortfolioHistoryPoint.self, from: Data(json.utf8))
        // 2025-12-14T00:00:00Z = 1765670400 since epoch.
        XCTAssertEqual(point.t.timeIntervalSince1970, 1765670400, accuracy: 0.001)
    }

    func test_decodesIso8601WithOffsetSuffix() throws {
        let json = #"""
        { "t": "2025-12-14T00:00:00+00:00", "v": "1000.00" }
        """#
        let point = try makeDecoder().decode(PortfolioHistoryPoint.self, from: Data(json.utf8))
        XCTAssertEqual(point.t.timeIntervalSince1970, 1765670400, accuracy: 0.001)
    }

    func test_decodesNegativeGain() throws {
        let json = #"""
        {
          "range": "1M",
          "timeframe": "1D",
          "currency": "USD",
          "base_value": "1000.00",
          "end_value": "950.00",
          "gain_abs": "-50.00",
          "gain_pct": "-0.05",
          "points": [
            { "t": "2025-11-14T00:00:00Z", "v": "1000.00" },
            { "t": "2025-12-14T00:00:00Z", "v": "950.00" }
          ]
        }
        """#
        let dto = try makeDecoder().decode(PortfolioHistoryDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.gainAbs, Decimal(string: "-50.00"))
        XCTAssertEqual(dto.gainPct, Decimal(string: "-0.05"))
    }
}
