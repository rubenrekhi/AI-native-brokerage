import XCTest
@testable import Sevino

@MainActor
final class PortfolioServiceTests: XCTestCase {

    // MARK: - historyPath

    func test_historyPath_appendsRangeQueryForOneDay() {
        XCTAssertEqual(
            PortfolioService.historyPath(for: .oneDay),
            "/v1/portfolio/history?range=1D"
        )
    }

    func test_historyPath_appendsRangeQueryForOneMonth() {
        XCTAssertEqual(
            PortfolioService.historyPath(for: .oneMonth),
            "/v1/portfolio/history?range=1M"
        )
    }

    func test_historyPath_appendsRangeQueryForYTD() {
        XCTAssertEqual(
            PortfolioService.historyPath(for: .ytd),
            "/v1/portfolio/history?range=YTD"
        )
    }

    // MARK: - normalize

    func test_normalize_emptyArray_returnsEmpty() {
        XCTAssertEqual(PortfolioService.normalize([]), [])
    }

    func test_normalize_singlePoint_returnsEmpty() {
        XCTAssertEqual(PortfolioService.normalize([Decimal(100)]), [])
    }

    func test_normalize_flatLine_returnsEmpty() {
        XCTAssertEqual(
            PortfolioService.normalize([Decimal(100), Decimal(100), Decimal(100)]),
            [],
            "Flat line has no range — returns empty so view renders no path"
        )
    }

    func test_normalize_twoPoints_returnsZeroAndOne() {
        let result = PortfolioService.normalize([Decimal(800), Decimal(1000)])

        XCTAssertEqual(result.count, 2)
        XCTAssertEqual(result[0], 0.0, accuracy: 0.0001)
        XCTAssertEqual(result[1], 1.0, accuracy: 0.0001)
    }

    func test_normalize_threePoints_centersInRange() {
        let result = PortfolioService.normalize([Decimal(800), Decimal(900), Decimal(1000)])

        XCTAssertEqual(result.count, 3)
        XCTAssertEqual(result[0], 0.0, accuracy: 0.0001)
        XCTAssertEqual(result[1], 0.5, accuracy: 0.0001)
        XCTAssertEqual(result[2], 1.0, accuracy: 0.0001)
    }

    func test_normalize_descendingValues_mapsCorrectly() {
        let result = PortfolioService.normalize([Decimal(1000), Decimal(900), Decimal(800)])

        XCTAssertEqual(result.count, 3)
        XCTAssertEqual(result[0], 1.0, accuracy: 0.0001)
        XCTAssertEqual(result[1], 0.5, accuracy: 0.0001)
        XCTAssertEqual(result[2], 0.0, accuracy: 0.0001)
    }

    // MARK: - makeSnapshot — gain source rule

    func test_makeSnapshot_oneDay_usesSnapshotDailyChange() {
        let snapshot = Self.makeSnapshotDTO(
            equity: Decimal(string: "1290.00")!,
            dailyChangeAbs: Decimal(string: "12.50")!,
            dailyChangePct: Decimal(string: "0.0098")!
        )
        let history = Self.makeHistoryDTO(
            gainAbs: Decimal(string: "290.00")!,
            gainPct: Decimal(string: "0.2900")!
        )

        let result = PortfolioService.makeSnapshot(
            snapshot: snapshot,
            history: history,
            range: .oneDay
        )

        XCTAssertEqual(result.gainAbs, Decimal(string: "12.50"))
        XCTAssertEqual(result.gainPct, Decimal(string: "0.0098"))
    }

    func test_makeSnapshot_oneWeek_usesHistoryGain() {
        let snapshot = Self.makeSnapshotDTO(
            dailyChangeAbs: Decimal(string: "12.50")!,
            dailyChangePct: Decimal(string: "0.0098")!
        )
        let history = Self.makeHistoryDTO(
            gainAbs: Decimal(string: "75.00")!,
            gainPct: Decimal(string: "0.06")!
        )

        let result = PortfolioService.makeSnapshot(
            snapshot: snapshot,
            history: history,
            range: .oneWeek
        )

        XCTAssertEqual(result.gainAbs, Decimal(string: "75.00"))
        XCTAssertEqual(result.gainPct, Decimal(string: "0.06"))
    }

    func test_makeSnapshot_oneMonth_usesHistoryGain() {
        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(),
            history: Self.makeHistoryDTO(
                gainAbs: Decimal(string: "290.00")!,
                gainPct: Decimal(string: "0.2900")!
            ),
            range: .oneMonth
        )

        XCTAssertEqual(result.gainAbs, Decimal(string: "290.00"))
        XCTAssertEqual(result.gainPct, Decimal(string: "0.2900"))
    }

    func test_makeSnapshot_oneYear_usesHistoryGain() {
        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(),
            history: Self.makeHistoryDTO(
                gainAbs: Decimal(string: "1500.00")!,
                gainPct: Decimal(string: "1.50")!
            ),
            range: .oneYear
        )

        XCTAssertEqual(result.gainAbs, Decimal(string: "1500.00"))
        XCTAssertEqual(result.gainPct, Decimal(string: "1.50"))
    }

    // MARK: - makeSnapshot — field projection

    func test_makeSnapshot_equityComesFromSnapshot() {
        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(equity: Decimal(string: "1290.00")!),
            history: Self.makeHistoryDTO(endValue: Decimal(string: "9999.99")!),
            range: .oneMonth
        )

        XCTAssertEqual(result.equity, Decimal(string: "1290.00"),
                       "equity must come from snapshot's live equity, not history's end_value")
    }

    func test_makeSnapshot_currencyComesFromSnapshot() {
        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(currency: "USD"),
            history: Self.makeHistoryDTO(currency: "EUR"),
            range: .oneMonth
        )

        XCTAssertEqual(result.currency, "USD")
    }

    func test_makeSnapshot_chartValuesComeFromHistoryPoints() {
        let history = Self.makeHistoryDTO(points: [
            Self.makePoint(v: Decimal(800)),
            Self.makePoint(v: Decimal(900)),
            Self.makePoint(v: Decimal(1000))
        ])

        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(),
            history: history,
            range: .oneMonth
        )

        XCTAssertEqual(result.chartValues, [Decimal(800), Decimal(900), Decimal(1000)])
    }

    func test_makeSnapshot_chartPointsAreNormalized() {
        let history = Self.makeHistoryDTO(points: [
            Self.makePoint(v: Decimal(800)),
            Self.makePoint(v: Decimal(900)),
            Self.makePoint(v: Decimal(1000))
        ])

        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(),
            history: history,
            range: .oneMonth
        )

        XCTAssertEqual(result.chartPoints.count, 3)
        XCTAssertEqual(result.chartPoints[0], 0.0, accuracy: 0.0001)
        XCTAssertEqual(result.chartPoints[1], 0.5, accuracy: 0.0001)
        XCTAssertEqual(result.chartPoints[2], 1.0, accuracy: 0.0001)
    }

    func test_makeSnapshot_emptyHistoryPoints_chartArraysAreEmpty() {
        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(),
            history: Self.makeHistoryDTO(points: []),
            range: .oneMonth
        )

        XCTAssertEqual(result.chartValues, [])
        XCTAssertEqual(result.chartPoints, [])
        XCTAssertEqual(result.chartDates, [])
    }

    func test_makeSnapshot_chartDatesParallelToValues() {
        let t1 = Date(timeIntervalSince1970: 1700000000)
        let t2 = Date(timeIntervalSince1970: 1700001000)
        let t3 = Date(timeIntervalSince1970: 1700002000)
        let history = Self.makeHistoryDTO(points: [
            Self.makePoint(v: Decimal(800), t: t1),
            Self.makePoint(v: Decimal(900), t: t2),
            Self.makePoint(v: Decimal(1000), t: t3)
        ])

        let result = PortfolioService.makeSnapshot(
            snapshot: Self.makeSnapshotDTO(),
            history: history,
            range: .oneMonth
        )

        XCTAssertEqual(result.chartDates.count, 3)
        XCTAssertEqual(result.chartDates[0].timeIntervalSince1970, t1.timeIntervalSince1970, accuracy: 1)
        XCTAssertEqual(result.chartDates[1].timeIntervalSince1970, t2.timeIntervalSince1970, accuracy: 1)
        XCTAssertEqual(result.chartDates[2].timeIntervalSince1970, t3.timeIntervalSince1970, accuracy: 1)
    }

    // MARK: - fetchPortfolio integration (parallel fan-out)

    func test_fetchPortfolio_callsBothEndpoints() async throws {
        let api = PathKeyedAPIClient()
        api.responses["/v1/portfolio/snapshot"] = Self.makeSnapshotDTO()
        api.responses["/v1/portfolio/history?range=1M"] = Self.makeHistoryDTO()
        let service = PortfolioService(api: api)

        _ = try await service.fetchPortfolio(for: .oneMonth)

        XCTAssertTrue(api.requestedPaths.contains("/v1/portfolio/snapshot"))
        XCTAssertTrue(api.requestedPaths.contains("/v1/portfolio/history?range=1M"))
    }

    func test_fetchPortfolio_passesRangeToHistoryPath() async throws {
        let api = PathKeyedAPIClient()
        api.responses["/v1/portfolio/snapshot"] = Self.makeSnapshotDTO()
        api.responses["/v1/portfolio/history?range=1Y"] = Self.makeHistoryDTO()
        let service = PortfolioService(api: api)

        _ = try await service.fetchPortfolio(for: .oneYear)

        XCTAssertTrue(api.requestedPaths.contains("/v1/portfolio/history?range=1Y"))
    }

    func test_fetchPortfolio_propagatesAPIError() async {
        let api = PathKeyedAPIClient()
        api.errorToThrow = URLError(.notConnectedToInternet)
        let service = PortfolioService(api: api)

        do {
            _ = try await service.fetchPortfolio(for: .oneMonth)
            XCTFail("Expected error to propagate")
        } catch {
            XCTAssertNotNil(error)
        }
    }

    // MARK: - Helpers

    private static func makeSnapshotDTO(
        equity: Decimal = Decimal(string: "1000.00")!,
        currency: String = "USD",
        dailyChangeAbs: Decimal = Decimal(string: "0")!,
        dailyChangePct: Decimal = Decimal(string: "0")!
    ) -> PortfolioSnapshotDTO {
        // DTOs use @DecimalString wrappers. The simplest reliable way to
        // construct one in tests is to round-trip through JSON — keeps
        // wrapper internals out of the tests.
        let json = """
        {
          "account_status": "ACTIVE",
          "currency": "\(currency)",
          "equity": "\(equity)",
          "last_equity": "\(equity)",
          "cash": "0",
          "buying_power": "0",
          "daily_change_abs": "\(dailyChangeAbs)",
          "daily_change_pct": "\(dailyChangePct)"
        }
        """
        let decoder = JSONDecoder.sevino()
        // swiftlint:disable:next force_try
        return try! decoder.decode(PortfolioSnapshotDTO.self, from: Data(json.utf8))
    }

    private static func makeHistoryDTO(
        currency: String = "USD",
        baseValue: Decimal = Decimal(string: "1000.00")!,
        endValue: Decimal = Decimal(string: "1000.00")!,
        gainAbs: Decimal = Decimal(string: "0")!,
        gainPct: Decimal = Decimal(string: "0")!,
        points: [PortfolioHistoryPoint] = []
    ) -> PortfolioHistoryDTO {
        let pointsJSON = points.map { p in
            "{\"t\":\"\(ISO8601DateFormatter().string(from: p.t))\",\"v\":\"\(p.v)\"}"
        }.joined(separator: ",")
        let json = """
        {
          "range": "1M",
          "timeframe": "1D",
          "currency": "\(currency)",
          "base_value": "\(baseValue)",
          "end_value": "\(endValue)",
          "gain_abs": "\(gainAbs)",
          "gain_pct": "\(gainPct)",
          "points": [\(pointsJSON)]
        }
        """
        let decoder = JSONDecoder.sevino()
        // swiftlint:disable:next force_try
        return try! decoder.decode(PortfolioHistoryDTO.self, from: Data(json.utf8))
    }

    private static func makePoint(v: Decimal, t: Date = Date(timeIntervalSince1970: 1700000000)) -> PortfolioHistoryPoint {
        let json = """
        { "t": "\(ISO8601DateFormatter().string(from: t))", "v": "\(v)" }
        """
        let decoder = JSONDecoder.sevino()
        // swiftlint:disable:next force_try
        return try! decoder.decode(PortfolioHistoryPoint.self, from: Data(json.utf8))
    }
}

/// Path-keyed fake API client — returns different responses per path so we
/// can exercise `PortfolioService`'s parallel fan-out (`async let snap` /
/// `async let hist`) without sharing one response across two endpoints.
private final class PathKeyedAPIClient: APIClientProtocol, @unchecked Sendable {
    var responses: [String: Any] = [:]
    var errorToThrow: Error?
    private(set) var requestedPaths: [String] = []

    func get<T: Decodable>(_ path: String) async throws -> T {
        requestedPaths.append(path)
        if let error = errorToThrow { throw error }
        guard let response = responses[path] as? T else {
            throw URLError(.badServerResponse)
        }
        return response
    }

    func post<T: Decodable>(_ path: String) async throws -> T { fatalError("unused") }
    func post<T: Decodable>(_ path: String, body: some Encodable) async throws -> T { fatalError("unused") }
    func post(_ path: String) async throws { fatalError("unused") }
    func post(_ path: String, body: some Encodable) async throws { fatalError("unused") }
    func put<T: Decodable>(_ path: String, body: some Encodable) async throws -> T { fatalError("unused") }
    func patch<T: Decodable>(_ path: String, body: some Encodable) async throws -> T { fatalError("unused") }
    func delete<T: Decodable>(_ path: String) async throws -> T { fatalError("unused") }
    func delete(_ path: String) async throws { fatalError("unused") }
    func delete(_ path: String, body: some Encodable) async throws { fatalError("unused") }
    func downloadFile(_ path: String, suggestedExtension: String?) async throws -> URL { fatalError("unused") }
}
