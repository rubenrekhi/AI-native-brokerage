import XCTest
@testable import Sevino

@MainActor
final class APIPortfolioHistoryServiceTests: XCTestCase {

    private var mockClient: MockAPIClient!
    private var service: APIPortfolioHistoryService!

    override func setUp() {
        mockClient = MockAPIClient()
        service = APIPortfolioHistoryService(client: mockClient)
    }

    func test_fetchHistory_hitsHistoryEndpointWithRange() async throws {
        mockClient.responseToReturn = Self.makeHistoryDTO(
            range: "1M",
            points: [("2025-11-14T00:00:00Z", "1000.00"), ("2025-12-14T00:00:00Z", "1290.00")]
        )

        _ = try await service.fetchHistory(for: .oneMonth)

        XCTAssertEqual(mockClient.lastPath, "/v1/portfolio/history")
        XCTAssertEqual(mockClient.lastMethod, "GET")
        XCTAssertEqual(mockClient.lastQuery, ["range": "1M"])
    }

    func test_fetchHistory_encodesEachRangeCorrectly() async throws {
        let cases: [(TimeRange, String)] = [
            (.oneDay, "1D"), (.oneWeek, "1W"), (.oneMonth, "1M"),
            (.threeMonths, "3M"), (.sixMonths, "6M"), (.ytd, "YTD"),
            (.oneYear, "1Y"), (.all, "ALL"),
        ]
        for (range, expected) in cases {
            mockClient.responseToReturn = Self.makeHistoryDTO(range: expected, points: [])
            _ = try await service.fetchHistory(for: range)
            XCTAssertEqual(mockClient.lastQuery, ["range": expected],
                           "TimeRange.\(range) should encode as \(expected)")
        }
    }

    func test_fetchHistory_normalizesPointsIntoZeroOneRange() async throws {
        mockClient.responseToReturn = Self.makeHistoryDTO(
            range: "1M",
            points: [
                ("2025-11-14T00:00:00Z", "100.00"),
                ("2025-11-21T00:00:00Z", "150.00"),
                ("2025-11-28T00:00:00Z", "200.00"),
            ]
        )

        let series = try await service.fetchHistory(for: .oneMonth)

        XCTAssertEqual(series.chartPoints.count, 3)
        XCTAssertEqual(series.chartPoints[0], 0.0, accuracy: 0.0001)
        XCTAssertEqual(series.chartPoints[1], 0.5, accuracy: 0.0001)
        XCTAssertEqual(series.chartPoints[2], 1.0, accuracy: 0.0001)
    }

    func test_fetchHistory_flatSeriesCollapsesToMidpoint() async throws {
        mockClient.responseToReturn = Self.makeHistoryDTO(
            range: "1M",
            points: [
                ("2025-11-14T00:00:00Z", "100.00"),
                ("2025-11-21T00:00:00Z", "100.00"),
                ("2025-11-28T00:00:00Z", "100.00"),
            ]
        )

        let series = try await service.fetchHistory(for: .oneMonth)

        XCTAssertEqual(series.chartPoints, [0.5, 0.5, 0.5])
    }

    func test_fetchHistory_emptyPointsReturnsEmptyChart() async throws {
        mockClient.responseToReturn = Self.makeHistoryDTO(range: "1D", points: [])

        let series = try await service.fetchHistory(for: .oneDay)

        XCTAssertEqual(series.chartPoints, [])
        XCTAssertEqual(series.points, [])
    }

    func test_fetchHistory_passesThroughMetadata() async throws {
        mockClient.responseToReturn = Self.makeHistoryDTO(
            range: "1M",
            baseValue: "1000.00",
            endValue: "1290.00",
            gainAbs: "290.00",
            gainPct: "0.2900",
            points: [("2025-11-14T00:00:00Z", "1000.00")]
        )

        let series = try await service.fetchHistory(for: .oneMonth)

        XCTAssertEqual(series.range, .oneMonth)
        XCTAssertEqual(series.baseValue, Decimal(string: "1000.00"))
        XCTAssertEqual(series.endValue, Decimal(string: "1290.00"))
        XCTAssertEqual(series.gainAbs, Decimal(string: "290.00"))
        XCTAssertEqual(series.gainPct, Decimal(string: "0.2900"))
    }

    // MARK: - Helpers

    private static func makeHistoryDTO(
        range: String,
        timeframe: String = "1D",
        currency: String = "USD",
        baseValue: String = "0",
        endValue: String = "0",
        gainAbs: String = "0",
        gainPct: String = "0",
        points: [(String, String)]
    ) -> PortfolioHistoryDTO {
        let pointsJson = points
            .map { #"{ "t": "\#($0.0)", "v": "\#($0.1)" }"# }
            .joined(separator: ",")
        let json = """
        {
          "range": "\(range)",
          "timeframe": "\(timeframe)",
          "currency": "\(currency)",
          "base_value": "\(baseValue)",
          "end_value": "\(endValue)",
          "gain_abs": "\(gainAbs)",
          "gain_pct": "\(gainPct)",
          "points": [\(pointsJson)]
        }
        """
        let decoder = APIClient.makeDecoder()
        // swiftlint:disable:next force_try
        return try! decoder.decode(PortfolioHistoryDTO.self, from: Data(json.utf8))
    }
}
