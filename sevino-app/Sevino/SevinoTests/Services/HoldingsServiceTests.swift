import XCTest
@testable import Sevino

@MainActor
final class HoldingsMapperTests: XCTestCase {

    // MARK: - CASH row

    func test_cashRow_alwaysAtIndexZero_evenWithPositions() {
        let dto = Self.makeDTO(
            cash: Decimal(string: "500.00")!,
            buyingPower: Decimal(string: "400.00")!,
            positions: [Self.makePosition(symbol: "TSLA")]
        )

        let holdings = mapHoldings(dto)

        XCTAssertEqual(holdings.first?.ticker, "CASH")
        XCTAssertEqual(holdings.first?.isCash, true)
        XCTAssertEqual(holdings.first?.marketValue, Decimal(string: "500.00"))
        XCTAssertEqual(holdings.first?.buyingPower, Decimal(string: "400.00"))
        XCTAssertNil(holdings.first?.qty)
        XCTAssertNil(holdings.first?.unrealizedPl)
        XCTAssertNil(holdings.first?.changeToday)
        XCTAssertNil(holdings.first?.avgEntryPrice)
    }

    func test_positionRows_haveNilBuyingPower() {
        let dto = Self.makeDTO(
            cash: Decimal(string: "500.00")!,
            buyingPower: Decimal(string: "400.00")!,
            positions: [Self.makePosition(symbol: "TSLA")]
        )

        let holdings = mapHoldings(dto)

        XCTAssertEqual(holdings[1].ticker, "TSLA")
        XCTAssertNil(holdings[1].buyingPower)
    }

    func test_emptyPositions_returnsOnlyCashRow() {
        let dto = Self.makeDTO(cash: Decimal(string: "1000.00")!, positions: [])

        let holdings = mapHoldings(dto)

        XCTAssertEqual(holdings.count, 1)
        XCTAssertEqual(holdings[0].ticker, "CASH")
        XCTAssertEqual(holdings[0].marketValue, Decimal(string: "1000.00"))
    }

    // MARK: - Position passthrough

    func test_positionFields_passThroughAsDecimals() {
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
        XCTAssertEqual(position.qty, Decimal(57))
        XCTAssertEqual(position.marketValue, Decimal(string: "21748.18"))
        XCTAssertEqual(position.unrealizedPl, Decimal(string: "7418.90"))
        XCTAssertEqual(position.unrealizedPlpc, Decimal(string: "0.5174"))
        XCTAssertEqual(position.changeToday, Decimal(string: "734.73"))
        XCTAssertEqual(position.changeTodayPercent, Decimal(string: "0.0350"))
        XCTAssertEqual(position.avgEntryPrice, Decimal(string: "248.91"))
    }

    func test_negativePosition_signsPreserved() {
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

        XCTAssertEqual(position.unrealizedPl, Decimal(string: "-1049.32"))
        XCTAssertEqual(position.unrealizedPlpc, Decimal(string: "-0.0838"))
        XCTAssertEqual(position.changeToday, Decimal(string: "-89.21"))
        XCTAssertEqual(position.changeTodayPercent, Decimal(string: "-0.0077"))
    }

    func test_fractionalQty_passesThroughExactly() {
        let dto = Self.makeDTO(
            cash: Decimal(0),
            positions: [Self.makePosition(symbol: "TSLA", qty: Decimal(string: "0.125")!)]
        )

        XCTAssertEqual(mapHoldings(dto)[1].qty, Decimal(string: "0.125"))
    }

    func test_zeroChangeToday_passedThroughAsZero() {
        // Mirrors the backend's symmetric-zero invariant from PR #643:
        // when the server can't compute a usable previous close (e.g. brand
        // new listing), both fields are pinned to 0. The mapper now passes
        // them through as Decimal(0); the view formats them at render time.
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
        XCTAssertEqual(position.changeToday, Decimal(0))
        XCTAssertEqual(position.changeTodayPercent, Decimal(0))
    }

    // MARK: - Fixtures

    private static func makeDTO(
        cash: Decimal,
        buyingPower: Decimal = Decimal(0),
        positions: [PositionDTO]
    ) -> HoldingsDTO {
        let json: [String: Any] = [
            "account_status": "ACTIVE",
            "currency": "USD",
            "cash": "\(cash)",
            "buying_power": "\(buyingPower)",
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
        XCTAssertEqual(holdings[0].marketValue, Decimal(string: "500.00"))
        XCTAssertEqual(holdings[1].ticker, "TSLA")
        XCTAssertEqual(holdings[1].qty, Decimal(5))
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
          "buying_power": "450.00",
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
