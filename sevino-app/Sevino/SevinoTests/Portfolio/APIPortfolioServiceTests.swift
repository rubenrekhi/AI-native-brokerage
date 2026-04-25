import XCTest
@testable import Sevino

@MainActor
final class APIPortfolioServiceTests: XCTestCase {

    private var mockClient: MockAPIClient!
    private var service: APIPortfolioService!

    override func setUp() {
        mockClient = MockAPIClient()
        service = APIPortfolioService(client: mockClient)
    }

    func test_fetchPortfolio_hitsSnapshotEndpoint() async throws {
        mockClient.responseToReturn = Self.makeSnapshotDTO(
            equity: "1084.92",
            dailyChangeAbs: "232.82",
            dailyChangePct: "0.2731"
        )

        _ = try await service.fetchPortfolio(for: .oneMonth)

        XCTAssertEqual(mockClient.lastPath, "/v1/portfolio/snapshot")
        XCTAssertEqual(mockClient.lastMethod, "GET")
    }

    func test_fetchPortfolio_mapsDtoToSnapshotForGain() async throws {
        mockClient.responseToReturn = Self.makeSnapshotDTO(
            equity: "1084.92",
            dailyChangeAbs: "232.82",
            dailyChangePct: "0.2731"
        )

        let snapshot = try await service.fetchPortfolio(for: .oneMonth)

        XCTAssertEqual(snapshot.accountStatus, "ACTIVE")
        XCTAssertEqual(snapshot.equity, Decimal(string: "1084.92"))
        XCTAssertEqual(snapshot.displayValue, "$1,084.92")
        XCTAssertFalse(snapshot.isDown)
        XCTAssertEqual(snapshot.gainText, "+$232.82 (+27.31%)")
        XCTAssertEqual(snapshot.chartPoints, [],
                       "chart points come from the history endpoint (F4.8)")
    }

    func test_fetchPortfolio_mapsDtoToSnapshotForLoss() async throws {
        mockClient.responseToReturn = Self.makeSnapshotDTO(
            equity: "11500.00",
            dailyChangeAbs: "-1049.32",
            dailyChangePct: "-0.0838"
        )

        let snapshot = try await service.fetchPortfolio(for: .oneMonth)

        XCTAssertTrue(snapshot.isDown)
        XCTAssertEqual(snapshot.gainText, "-$1,049.32 (-8.38%)")
    }

    func test_fetchPortfolio_propagates409IncompleteOnboarding() async {
        mockClient.errorToThrow = APIError(
            error: "Onboarding incomplete",
            code: APIError.Code.incompleteOnboarding
        )

        do {
            _ = try await service.fetchPortfolio(for: .oneMonth)
            XCTFail("Expected APIError to propagate")
        } catch let error as APIError {
            XCTAssertEqual(error.code, APIError.Code.incompleteOnboarding)
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    func test_fetchPortfolio_propagates503AlpacaUnavailable() async {
        mockClient.errorToThrow = APIError(
            error: "Alpaca unavailable",
            code: APIError.Code.alpacaUnavailable
        )

        do {
            _ = try await service.fetchPortfolio(for: .oneMonth)
            XCTFail("Expected APIError to propagate")
        } catch let error as APIError {
            XCTAssertEqual(error.code, APIError.Code.alpacaUnavailable)
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    // MARK: - Helpers

    private static func makeSnapshotDTO(
        accountStatus: String = "ACTIVE",
        currency: String = "USD",
        equity: String,
        lastEquity: String = "0",
        cash: String = "0",
        buyingPower: String = "0",
        dailyChangeAbs: String,
        dailyChangePct: String
    ) -> PortfolioSnapshotDTO {
        let json = """
        {
          "account_status": "\(accountStatus)",
          "currency": "\(currency)",
          "equity": "\(equity)",
          "last_equity": "\(lastEquity)",
          "cash": "\(cash)",
          "buying_power": "\(buyingPower)",
          "daily_change_abs": "\(dailyChangeAbs)",
          "daily_change_pct": "\(dailyChangePct)"
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // swiftlint:disable:next force_try
        return try! decoder.decode(PortfolioSnapshotDTO.self, from: Data(json.utf8))
    }
}
