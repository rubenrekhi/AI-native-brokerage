import XCTest
@testable import Sevino

@MainActor
final class PortfolioSnapshotDTOTests: XCTestCase {

    private func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    func test_decodesActiveAccountFullPayload() throws {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "equity": "12500.50",
          "last_equity": "12000.00",
          "cash": "500.25",
          "buying_power": "1000.50",
          "daily_change_abs": "500.50",
          "daily_change_pct": "0.0417"
        }
        """#
        let dto = try makeDecoder().decode(PortfolioSnapshotDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.accountStatus, "ACTIVE")
        XCTAssertEqual(dto.currency, "USD")
        XCTAssertEqual(dto.equity, Decimal(string: "12500.50"))
        XCTAssertEqual(dto.lastEquity, Decimal(string: "12000.00"))
        XCTAssertEqual(dto.cash, Decimal(string: "500.25"))
        XCTAssertEqual(dto.buyingPower, Decimal(string: "1000.50"))
        XCTAssertEqual(dto.dailyChangeAbs, Decimal(string: "500.50"))
        XCTAssertEqual(dto.dailyChangePct, Decimal(string: "0.0417"))
    }

    func test_decodesPendingAccountWithZeros() throws {
        let json = #"""
        {
          "account_status": "APPROVAL_PENDING",
          "currency": "USD",
          "equity": "0",
          "last_equity": "0",
          "cash": "0",
          "buying_power": "0",
          "daily_change_abs": "0",
          "daily_change_pct": "0"
        }
        """#
        let dto = try makeDecoder().decode(PortfolioSnapshotDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.accountStatus, "APPROVAL_PENDING")
        XCTAssertEqual(dto.equity, Decimal(0))
        XCTAssertEqual(dto.dailyChangeAbs, Decimal(0))
    }

    func test_decodesNegativeDailyChange() throws {
        let json = #"""
        {
          "account_status": "ACTIVE",
          "currency": "USD",
          "equity": "11500.00",
          "last_equity": "12000.00",
          "cash": "500.00",
          "buying_power": "1000.00",
          "daily_change_abs": "-500.00",
          "daily_change_pct": "-0.0417"
        }
        """#
        let dto = try makeDecoder().decode(PortfolioSnapshotDTO.self, from: Data(json.utf8))
        XCTAssertEqual(dto.dailyChangeAbs, Decimal(string: "-500.00"))
        XCTAssertEqual(dto.dailyChangePct, Decimal(string: "-0.0417"))
    }
}
