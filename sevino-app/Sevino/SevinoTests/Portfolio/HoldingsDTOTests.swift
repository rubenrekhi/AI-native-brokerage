import XCTest
@testable import Sevino

@MainActor
final class HoldingsDTOTests: XCTestCase {

    private func makeDecoder() -> JSONDecoder {
        APIClient.makeDecoder()
    }

    func test_decodesTwoPositions() throws {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "cash": "500.00",
          "total_market_value": "12000.00",
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
              "unrealized_plpc": "0.25"
            },
            {
              "symbol": "AMD",
              "name": "Advanced Micro Devices",
              "qty": "10",
              "avg_entry_price": "100.00",
              "current_price": "120.00",
              "market_value": "1200.00",
              "cost_basis": "1000.00",
              "unrealized_pl": "200.00",
              "unrealized_plpc": "0.20"
            }
          ]
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.accountStatus, "ACTIVE")
        XCTAssertEqual(dto.cash, Decimal(string: "500.00"))
        XCTAssertEqual(dto.totalMarketValue, Decimal(string: "12000.00"))
        XCTAssertEqual(dto.positions.count, 2)
        XCTAssertEqual(dto.positions[0].symbol, "TSLA")
        XCTAssertEqual(dto.positions[0].name, "Tesla, Inc.")
        XCTAssertEqual(dto.positions[0].qty, Decimal(5))
        XCTAssertEqual(dto.positions[0].marketValue, Decimal(string: "1250.00"))
        XCTAssertEqual(dto.positions[1].symbol, "AMD")
    }

    func test_negativeUnrealizedPl_preservesSign() throws {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "cash": "500.00",
          "total_market_value": "800.00",
          "positions": [
            {
              "symbol": "TSLA",
              "name": "Tesla, Inc.",
              "qty": "5",
              "avg_entry_price": "200.00",
              "current_price": "160.00",
              "market_value": "800.00",
              "cost_basis": "1000.00",
              "unrealized_pl": "-200.00",
              "unrealized_plpc": "-0.20"
            }
          ]
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.positions[0].unrealizedPl, Decimal(string: "-200.00"))
        XCTAssertEqual(dto.positions[0].unrealizedPlpc, Decimal(string: "-0.20"))
    }

    func test_fractionalQtyRoundtripsThroughAsShareCount() throws {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "cash": "0",
          "total_market_value": "31.25",
          "positions": [
            {
              "symbol": "TSLA",
              "name": "Tesla, Inc.",
              "qty": "0.125",
              "avg_entry_price": "250.00",
              "current_price": "250.00",
              "market_value": "31.25",
              "cost_basis": "31.25",
              "unrealized_pl": "0",
              "unrealized_plpc": "0"
            }
          ]
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.positions[0].qty, Decimal(string: "0.125"))
        XCTAssertEqual(dto.positions[0].qty.asShareCount(), "0.125")
    }

    func test_decodesEmptyPositions() throws {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "cash": "1000.00",
          "total_market_value": "0",
          "positions": []
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.positions, [])
        XCTAssertEqual(dto.cash, Decimal(string: "1000.00"))
    }

    func test_decodesPendingAccountZeroShape() throws {
        let json = #"""
        {
          "account_status": "APPROVAL_PENDING",
          "currency": "USD",
          "cash": "0",
          "total_market_value": "0",
          "positions": []
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.accountStatus, "APPROVAL_PENDING")
        XCTAssertEqual(dto.cash, Decimal(0))
    }
}
