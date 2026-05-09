import XCTest
@testable import Sevino

@MainActor
final class HoldingsDTOTests: XCTestCase {

    private func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
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
              "unrealized_plpc": "0.25",
              "change_today": "25.00",
              "change_today_percent": "0.0204"
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
              "unrealized_plpc": "0.20",
              "change_today": "10.00",
              "change_today_percent": "0.0084"
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
        XCTAssertEqual(dto.positions[0].changeToday, Decimal(string: "25.00"))
        XCTAssertEqual(dto.positions[0].changeTodayPercent, Decimal(string: "0.0204"))
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
              "unrealized_plpc": "-0.20",
              "change_today": "-50.00",
              "change_today_percent": "-0.0588"
            }
          ]
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.positions[0].unrealizedPl, Decimal(string: "-200.00"))
        XCTAssertEqual(dto.positions[0].unrealizedPlpc, Decimal(string: "-0.20"))
        XCTAssertEqual(dto.positions[0].changeToday, Decimal(string: "-50.00"))
        XCTAssertEqual(dto.positions[0].changeTodayPercent, Decimal(string: "-0.0588"))
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
              "unrealized_plpc": "0",
              "change_today": "0",
              "change_today_percent": "0"
            }
          ]
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.positions[0].qty, Decimal(string: "0.125"))
        XCTAssertEqual(dto.positions[0].qty.asShareCount(), "0.125")
    }

    func test_changeTodayZerosWhenServerCannotComputePreviousClose() throws {
        // Mirrors the backend invariant: when lastday_price is missing
        // (e.g. brand new listing), the API zeros both $ and % together.
        // The DTO must decode "0.00" / "0.0000" cleanly.
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "cash": "100.00",
          "total_market_value": "100.00",
          "positions": [
            {
              "symbol": "NEW",
              "name": "New Listing",
              "qty": "1",
              "avg_entry_price": "100.00",
              "current_price": "100.00",
              "market_value": "100.00",
              "cost_basis": "100.00",
              "unrealized_pl": "0.00",
              "unrealized_plpc": "0.0000",
              "change_today": "0.00",
              "change_today_percent": "0.0000"
            }
          ]
        }
        """#
        let dto = try makeDecoder().decode(HoldingsDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.positions[0].changeToday, Decimal(0))
        XCTAssertEqual(dto.positions[0].changeTodayPercent, Decimal(0))
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
