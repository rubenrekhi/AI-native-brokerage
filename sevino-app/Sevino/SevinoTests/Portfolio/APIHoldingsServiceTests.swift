import XCTest
@testable import Sevino

@MainActor
final class APIHoldingsServiceTests: XCTestCase {

    private var mockClient: MockAPIClient!
    private var service: APIHoldingsService!

    override func setUp() {
        mockClient = MockAPIClient()
        service = APIHoldingsService(client: mockClient)
    }

    // MARK: - Endpoint wiring

    func testFetchHoldingsHitsCorrectEndpoint() async throws {
        mockClient.responseToReturn = Self.activeDTO()

        _ = try await service.fetchHoldings()

        XCTAssertEqual(mockClient.lastPath, "/v1/portfolio/holdings")
        XCTAssertEqual(mockClient.lastMethod, "GET")
    }

    // MARK: - Cash + positions mapping

    func testFetchHoldingsPrependsCashRow() async throws {
        mockClient.responseToReturn = Self.activeDTO()

        let holdings = try await service.fetchHoldings()

        XCTAssertEqual(holdings.count, 3)
        let cash = holdings[0]
        XCTAssertTrue(cash.isCash)
        XCTAssertEqual(cash.ticker, "CASH")
        XCTAssertEqual(cash.name, "Cash")
        XCTAssertEqual(cash.marketValue, Decimal(string: "40291.92"))
        XCTAssertEqual(cash.valueText, Decimal(string: "40291.92")!.asCurrency())
        XCTAssertNil(cash.qty)
        XCTAssertNil(cash.unrealizedPl)
    }

    func testFetchHoldingsMapsPositiveGainPosition() async throws {
        mockClient.responseToReturn = Self.activeDTO()

        let holdings = try await service.fetchHoldings()

        let tsla = holdings[1]
        XCTAssertFalse(tsla.isCash)
        XCTAssertEqual(tsla.ticker, "TSLA")
        XCTAssertEqual(tsla.name, "Tesla, Inc.")
        XCTAssertEqual(tsla.qty, Decimal(string: "57"))
        XCTAssertEqual(tsla.marketValue, Decimal(string: "21748.18"))
        XCTAssertEqual(tsla.unrealizedPl, Decimal(string: "7460.16"))
        XCTAssertEqual(tsla.unrealizedPlpc, Decimal(string: "0.5221"))
        XCTAssertEqual(tsla.isPositive, true)
        let expectedPL = Decimal(string: "7460.16")!.asSignedCurrency()
        let expectedPct = Decimal(string: "0.5221")!.asSignedPercent()
        XCTAssertEqual(tsla.gainLossText, "\(expectedPL) (\(expectedPct))")
    }

    func testFetchHoldingsMapsNegativeGainPosition() async throws {
        mockClient.responseToReturn = Self.activeDTO()

        let holdings = try await service.fetchHoldings()

        let amd = holdings[2]
        XCTAssertEqual(amd.ticker, "AMD")
        XCTAssertEqual(amd.unrealizedPl, Decimal(string: "-1009.32"))
        XCTAssertEqual(amd.isPositive, false)
        let expectedPL = Decimal(string: "-1009.32")!.asSignedCurrency()
        let expectedPct = Decimal(string: "-0.0809")!.asSignedPercent()
        XCTAssertEqual(amd.gainLossText, "\(expectedPL) (\(expectedPct))")
    }

    // MARK: - Edge cases

    func testFetchHoldingsEmptyPositionsReturnsCashOnly() async throws {
        mockClient.responseToReturn = HoldingsDTOFactory.make(
            cash: Decimal(0),
            totalMarketValue: Decimal(0),
            positions: []
        )

        let holdings = try await service.fetchHoldings()

        XCTAssertEqual(holdings.count, 1)
        XCTAssertTrue(holdings[0].isCash)
        XCTAssertEqual(holdings[0].marketValue, Decimal(0))
        XCTAssertEqual(holdings[0].valueText, Decimal(0).asCurrency())
    }

    func testFetchHoldingsPendingAccountReturnsZeroCashRow() async throws {
        mockClient.responseToReturn = HoldingsDTOFactory.make(
            accountStatus: "APPROVAL_PENDING",
            cash: Decimal(0),
            totalMarketValue: Decimal(0),
            positions: []
        )

        let holdings = try await service.fetchHoldings()

        XCTAssertEqual(holdings.count, 1)
        XCTAssertEqual(holdings[0].marketValue, Decimal(0))
    }

    // MARK: - Error propagation

    func testFetchHoldingsPropagatesError() async {
        mockClient.errorToThrow = APIError(error: "Account not active", code: "ACCOUNT_NOT_ACTIVE", detail: nil)

        do {
            _ = try await service.fetchHoldings()
            XCTFail("Expected APIError to propagate")
        } catch let apiError as APIError {
            XCTAssertEqual(apiError.code, "ACCOUNT_NOT_ACTIVE")
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    // MARK: - Fixture

    private static func activeDTO() -> HoldingsDTO {
        HoldingsDTOFactory.make(
            accountStatus: "ACTIVE",
            cash: Decimal(string: "40291.92")!,
            totalMarketValue: Decimal(string: "33213.37")!,
            positions: [
                HoldingsDTOFactory.makePosition(
                    symbol: "TSLA", name: "Tesla, Inc.",
                    qty: Decimal(57),
                    avgEntryPrice: Decimal(string: "248.91")!,
                    currentPrice: Decimal(string: "381.55")!,
                    marketValue: Decimal(string: "21748.18")!,
                    costBasis: Decimal(string: "14288.02")!,
                    unrealizedPl: Decimal(string: "7460.16")!,
                    unrealizedPlpc: Decimal(string: "0.5221")!
                ),
                HoldingsDTOFactory.makePosition(
                    symbol: "AMD", name: "Advanced Micro Devices",
                    qty: Decimal(37),
                    avgEntryPrice: Decimal(string: "338.23")!,
                    currentPrice: Decimal(string: "309.85")!,
                    marketValue: Decimal(string: "11465.19")!,
                    costBasis: Decimal(string: "12474.51")!,
                    unrealizedPl: Decimal(string: "-1009.32")!,
                    unrealizedPlpc: Decimal(string: "-0.0809")!
                ),
            ]
        )
    }
}

/// `@DecimalString` properties have private `_x` storage, so direct memberwise
/// init from tests doesn't compile. We construct the DTOs by decoding a JSON
/// blob that mirrors the on-the-wire shape.
private enum HoldingsDTOFactory {
    static func make(
        accountStatus: String = "ACTIVE",
        currency: String = "USD",
        cash: Decimal,
        totalMarketValue: Decimal,
        positions: [PositionDTO]
    ) -> HoldingsDTO {
        let positionsJSON = positions.map { p in
            #"""
            {
              "symbol": "\#(p.symbol)",
              "name": "\#(p.name)",
              "qty": "\#(p.qty)",
              "avg_entry_price": "\#(p.avgEntryPrice)",
              "current_price": "\#(p.currentPrice)",
              "market_value": "\#(p.marketValue)",
              "cost_basis": "\#(p.costBasis)",
              "unrealized_pl": "\#(p.unrealizedPl)",
              "unrealized_plpc": "\#(p.unrealizedPlpc)"
            }
            """#
        }.joined(separator: ",")
        let json = #"""
        {
          "account_status": "\#(accountStatus)",
          "currency": "\#(currency)",
          "cash": "\#(cash)",
          "total_market_value": "\#(totalMarketValue)",
          "positions": [\#(positionsJSON)]
        }
        """#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(HoldingsDTO.self, from: Data(json.utf8))
    }

    static func makePosition(
        symbol: String,
        name: String,
        qty: Decimal,
        avgEntryPrice: Decimal,
        currentPrice: Decimal,
        marketValue: Decimal,
        costBasis: Decimal,
        unrealizedPl: Decimal,
        unrealizedPlpc: Decimal
    ) -> PositionDTO {
        let json = #"""
        {
          "symbol": "\#(symbol)",
          "name": "\#(name)",
          "qty": "\#(qty)",
          "avg_entry_price": "\#(avgEntryPrice)",
          "current_price": "\#(currentPrice)",
          "market_value": "\#(marketValue)",
          "cost_basis": "\#(costBasis)",
          "unrealized_pl": "\#(unrealizedPl)",
          "unrealized_plpc": "\#(unrealizedPlpc)"
        }
        """#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(PositionDTO.self, from: Data(json.utf8))
    }
}
