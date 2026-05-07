import XCTest
@testable import Sevino

@MainActor
final class HoldingsMapperTests: XCTestCase {

    // MARK: - CASH row

    func test_cashRow_alwaysAtIndexZero_evenWithPositions() {
        let dto = Self.makeDTO(
            cash: Decimal(string: "500.00")!,
            positions: [Self.makePosition(symbol: "TSLA")]
        )

        let holdings = mapHoldings(dto)

        XCTAssertEqual(holdings.first?.ticker, "CASH")
        XCTAssertEqual(holdings.first?.isCash, true)
        XCTAssertEqual(holdings.first?.value, "$500.00")
    }

    func test_emptyPositions_returnsOnlyCashRow() {
        let dto = Self.makeDTO(cash: Decimal(string: "1000.00")!, positions: [])

        let holdings = mapHoldings(dto)

        XCTAssertEqual(holdings.count, 1)
        XCTAssertEqual(holdings[0].ticker, "CASH")
        XCTAssertEqual(holdings[0].value, "$1,000.00")
    }

    // MARK: - Position formatting

    func test_positivePosition_formatsAllFields() {
        let dto = Self.makeDTO(
            cash: Decimal(0),
            positions: [
                Self.makePosition(
                    symbol: "TSLA",
                    qty: Decimal(57),
                    avgEntryPrice: Decimal(string: "248.91")!,
                    marketValue: Decimal(string: "21748.18")!,
                    unrealizedPl: Decimal(string: "7418.90")!,
                    unrealizedPlpc: Decimal(string: "0.5174")!,
                    changeToday: Decimal(string: "734.73")!,
                    changeTodayPercent: Decimal(string: "0.0350")!
                )
            ]
        )

        let position = mapHoldings(dto)[1]

        XCTAssertEqual(position.ticker, "TSLA")
        XCTAssertEqual(position.isCash, false)
        XCTAssertEqual(position.shares, "57")
        XCTAssertEqual(position.value, "$21,748.18")
        XCTAssertEqual(position.gainLossText, "+$7,418.90 (+51.74%)")
        XCTAssertEqual(position.isPositive, true)
        XCTAssertEqual(position.daysGain, "+$734.73")
        XCTAssertEqual(position.daysGainPercent, "+3.50%")
        XCTAssertEqual(position.totalGain, "+$7,418.90")
        XCTAssertEqual(position.totalGainPercent, "+51.74%")
        XCTAssertEqual(position.averageCost, "$248.91")
    }

    func test_negativePosition_setsIsPositiveFalseAndPreservesSigns() {
        let dto = Self.makeDTO(
            cash: Decimal(0),
            positions: [
                Self.makePosition(
                    symbol: "AMD",
                    unrealizedPl: Decimal(string: "-1049.32")!,
                    unrealizedPlpc: Decimal(string: "-0.0838")!,
                    changeToday: Decimal(string: "-89.21")!,
                    changeTodayPercent: Decimal(string: "-0.0077")!
                )
            ]
        )

        let position = mapHoldings(dto)[1]

        XCTAssertEqual(position.isPositive, false)
        XCTAssertEqual(position.gainLossText, "-$1,049.32 (-8.38%)")
        XCTAssertEqual(position.daysGain, "-$89.21")
        XCTAssertEqual(position.daysGainPercent, "-0.77%")
        XCTAssertEqual(position.totalGain, "-$1,049.32")
        XCTAssertEqual(position.totalGainPercent, "-8.38%")
    }

    func test_fractionalQty_rendersWithoutTrailingZeros() {
        let dto = Self.makeDTO(
            cash: Decimal(0),
            positions: [Self.makePosition(symbol: "TSLA", qty: Decimal(string: "0.125")!)]
        )

        XCTAssertEqual(mapHoldings(dto)[1].shares, "0.125")
    }

    func test_zeroGain_isPositiveTrue() {
        // unrealized_pl == 0 is treated as neutral/positive: the gain row
        // renders with the positive style (not the loss-red color).
        let dto = Self.makeDTO(
            cash: Decimal(0),
            positions: [Self.makePosition(symbol: "AAPL", unrealizedPl: Decimal(0))]
        )

        XCTAssertEqual(mapHoldings(dto)[1].isPositive, true)
    }

    func test_zeroChangeToday_rendersSymmetricZeroPair() {
        // Mirrors the backend's symmetric-zero invariant from PR #643:
        // when the server can't compute a usable previous close
        // (e.g. brand new listing), both change_today and
        // change_today_percent are pinned to 0. NumberFormatter treats
        // zero as positive, so the mapper currently renders "+$0.00 /
        // +0.00%". Pin that here so a future formatter tweak doesn't
        // silently change what users see on a "no data" day.
        let dto = Self.makeDTO(
            cash: Decimal(0),
            positions: [
                Self.makePosition(
                    symbol: "NEW",
                    changeToday: Decimal(0),
                    changeTodayPercent: Decimal(0)
                )
            ]
        )

        let position = mapHoldings(dto)[1]

        XCTAssertEqual(position.daysGain, "+$0.00")
        XCTAssertEqual(position.daysGainPercent, "+0.00%")
    }

    // MARK: - Fixtures

    private static func makeDTO(
        cash: Decimal,
        positions: [PositionDTO]
    ) -> HoldingsDTO {
        let json: [String: Any] = [
            "account_status": "ACTIVE",
            "currency": "USD",
            "cash": "\(cash)",
            "total_market_value": "0.00",
            "positions": positions.map(positionAsDict),
        ]
        let data = try! JSONSerialization.data(withJSONObject: json)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(HoldingsDTO.self, from: data)
    }

    private static func makePosition(
        symbol: String,
        qty: Decimal = Decimal(1),
        avgEntryPrice: Decimal = Decimal(string: "100.00")!,
        marketValue: Decimal = Decimal(string: "100.00")!,
        unrealizedPl: Decimal = Decimal(0),
        unrealizedPlpc: Decimal = Decimal(0),
        changeToday: Decimal = Decimal(0),
        changeTodayPercent: Decimal = Decimal(0)
    ) -> PositionDTO {
        let json: [String: Any] = [
            "symbol": symbol,
            "name": symbol,
            "qty": "\(qty)",
            "avg_entry_price": "\(avgEntryPrice)",
            "current_price": "\(marketValue)",
            "market_value": "\(marketValue)",
            "cost_basis": "\(marketValue)",
            "unrealized_pl": "\(unrealizedPl)",
            "unrealized_plpc": "\(unrealizedPlpc)",
            "change_today": "\(changeToday)",
            "change_today_percent": "\(changeTodayPercent)",
        ]
        let data = try! JSONSerialization.data(withJSONObject: json)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(PositionDTO.self, from: data)
    }

    private static func positionAsDict(_ p: PositionDTO) -> [String: Any] {
        [
            "symbol": p.symbol,
            "name": p.name,
            "qty": "\(p.qty)",
            "avg_entry_price": "\(p.avgEntryPrice)",
            "current_price": "\(p.currentPrice)",
            "market_value": "\(p.marketValue)",
            "cost_basis": "\(p.costBasis)",
            "unrealized_pl": "\(p.unrealizedPl)",
            "unrealized_plpc": "\(p.unrealizedPlpc)",
            "change_today": "\(p.changeToday)",
            "change_today_percent": "\(p.changeTodayPercent)",
        ]
    }
}

@MainActor
final class APIHoldingsServiceTests: XCTestCase {

    private var mockAPI: MockAPIClient!
    private var service: APIHoldingsService!

    override func setUp() {
        mockAPI = MockAPIClient()
        service = APIHoldingsService(api: mockAPI)
    }

    func test_fetchHoldings_callsCorrectPath() async throws {
        mockAPI.responseToReturn = Self.dtoFixture()

        _ = try await service.fetchHoldings()

        XCTAssertEqual(mockAPI.lastPath, "/v1/portfolio/holdings")
        XCTAssertEqual(mockAPI.lastMethod, "GET")
    }

    func test_fetchHoldings_runsResponseThroughMapper() async throws {
        mockAPI.responseToReturn = Self.dtoFixture()

        let holdings = try await service.fetchHoldings()

        // CASH always at index 0; one position from the fixture follows.
        XCTAssertEqual(holdings.count, 2)
        XCTAssertEqual(holdings[0].ticker, "CASH")
        XCTAssertEqual(holdings[0].value, "$500.00")
        XCTAssertEqual(holdings[1].ticker, "TSLA")
        XCTAssertEqual(holdings[1].shares, "5")
    }

    func test_fetchHoldings_propagatesAPIClientError() async {
        mockAPI.errorToThrow = URLError(.notConnectedToInternet)

        do {
            _ = try await service.fetchHoldings()
            XCTFail("Expected error to propagate")
        } catch let error as URLError {
            XCTAssertEqual(error.code, .notConnectedToInternet)
        } catch {
            XCTFail("Expected URLError, got \(error)")
        }
    }

    private static func dtoFixture() -> HoldingsDTO {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "cash": "500.00",
          "total_market_value": "1250.00",
          "positions": [
            {
              "symbol": "TSLA",
              "name": "Tesla, Inc.",
              "qty": "5",
              "avg_entry_price": "200.00",
              "current_price": "250.00",
              "market_value": "1250.00",
              "cost_basis": "1000.00",
              "unrealized_pl": "250.00",
              "unrealized_plpc": "0.25",
              "change_today": "25.00",
              "change_today_percent": "0.0204"
            }
          ]
        }
        """#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(HoldingsDTO.self, from: Data(json.utf8))
    }
}
