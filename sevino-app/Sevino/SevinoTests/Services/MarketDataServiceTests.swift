import XCTest
@testable import Sevino

final class MarketDataServiceTests: XCTestCase {

    private var session: URLSession!

    override func setUp() {
        super.setUp()
        session = StubURLProtocol.makeSession()
    }

    override func tearDown() {
        StubURLProtocol.reset()
        session = nil
        super.tearDown()
    }

    // MARK: - getStockInfo

    func test_getStockInfo_hitsExpectedPath() async throws {
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = Self.stubStockInfoResponse()
        let service = MarketDataService(api: mockAPI)

        _ = try await service.getStockInfo(symbol: "AAPL")

        XCTAssertEqual(mockAPI.lastMethod, "GET")
        XCTAssertEqual(mockAPI.lastPath, "/v1/market-data/stocks/AAPL")
    }

    func test_getStockInfo_propagatesAPIError() async {
        let mockAPI = MockAPIClient()
        mockAPI.errorToThrow = URLError(.notConnectedToInternet)
        let service = MarketDataService(api: mockAPI)

        do {
            _ = try await service.getStockInfo(symbol: "AAPL")
            XCTFail("Expected error")
        } catch {
            XCTAssertTrue(error is URLError)
        }
    }

    // MARK: - getBatchQuotes

    func test_getBatchQuotes_joinsSymbolsWithCommas() async throws {
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = BatchQuoteResponse(quotes: [])
        let service = MarketDataService(api: mockAPI)

        _ = try await service.getBatchQuotes(symbols: ["AAPL", "TSLA", "MSFT"])

        XCTAssertEqual(mockAPI.lastMethod, "GET")
        XCTAssertEqual(mockAPI.lastPath, "/v1/market-data/stocks/batch?symbols=AAPL,TSLA,MSFT")
    }

    func test_getBatchQuotes_percentEncodesSpecialSymbols() async throws {
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = BatchQuoteResponse(quotes: [])
        let service = MarketDataService(api: mockAPI)

        _ = try await service.getBatchQuotes(symbols: ["BRK.B", "BF.B"])

        // URLComponents leaves `.` unencoded but encodes the path's reserved chars.
        XCTAssertEqual(mockAPI.lastPath, "/v1/market-data/stocks/batch?symbols=BRK.B,BF.B")
    }

    func test_getBatchQuotes_decodesQuotes() async throws {
        let body = Data(#"""
        {
          "quotes": [
            {
              "symbol": "AAPL",
              "name": "Apple Inc.",
              "price": "184.20",
              "change": "1.50",
              "change_percent": "0.82",
              "open": "183.00",
              "day_high": "185.00",
              "day_low": "182.50",
              "previous_close": "182.70",
              "volume": 50000000,
              "avg_volume": 60000000,
              "market_cap": 3000000000000,
              "pe_ratio": "30.0",
              "eps": "6.10",
              "year_high": "200.00",
              "year_low": "150.00",
              "price_avg_50": "180.00",
              "price_avg_200": "175.00",
              "shares_outstanding": 16000000000,
              "earnings_announcement": null,
              "timestamp": 1714320000
            }
          ]
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/market-data/stocks/batch",
            response: .success(status: 200, body: body)
        )

        let service = makeService()
        let response = try await service.getBatchQuotes(symbols: ["AAPL"])

        XCTAssertEqual(response.quotes.count, 1)
        XCTAssertEqual(response.quotes[0].symbol, "AAPL")
        XCTAssertEqual(response.quotes[0].priceValue, Decimal(string: "184.20"))
        XCTAssertFalse(response.quotes[0].isNegativeChange)
    }

    // MARK: - getChart

    func test_getChart_includesTimeframeQueryParam() async throws {
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = ChartResponse(symbol: "AAPL", timeframe: "1M", bars: [])
        let service = MarketDataService(api: mockAPI)

        _ = try await service.getChart(symbol: "AAPL", timeframe: .oneMonth)

        XCTAssertEqual(mockAPI.lastMethod, "GET")
        XCTAssertEqual(mockAPI.lastPath, "/v1/market-data/stocks/AAPL/chart?timeframe=1M")
    }

    func test_getChart_supportsAllTimeframes() async throws {
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = ChartResponse(symbol: "AAPL", timeframe: "1D", bars: [])
        let service = MarketDataService(api: mockAPI)

        for timeframe in ChartTimeframe.allCases {
            _ = try await service.getChart(symbol: "AAPL", timeframe: timeframe)
            XCTAssertEqual(
                mockAPI.lastPath,
                "/v1/market-data/stocks/AAPL/chart?timeframe=\(timeframe.rawValue)"
            )
        }
    }

    // MARK: - getMarketStatus

    func test_getMarketStatus_hitsExpectedPath() async throws {
        let mockAPI = MockAPIClient()
        mockAPI.responseToReturn = MarketStatusResponse(
            isOpen: true,
            nextOpen: "2026-05-07T13:30:00Z",
            nextClose: "2026-05-06T20:00:00Z",
            timestamp: "2026-05-06T15:00:00Z"
        )
        let service = MarketDataService(api: mockAPI)

        _ = try await service.getMarketStatus()

        XCTAssertEqual(mockAPI.lastMethod, "GET")
        XCTAssertEqual(mockAPI.lastPath, "/v1/market-data/market/status")
    }

    func test_getMarketStatus_propagatesAPIError() async {
        let errorBody = Data(#"{"error":"Forbidden","code":"FORBIDDEN"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/market-data/market/status",
            response: .success(status: 403, body: errorBody)
        )

        let service = makeService()
        do {
            _ = try await service.getMarketStatus()
            XCTFail("expected APIError")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "FORBIDDEN")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - Helpers

    private func makeService() -> MarketDataService {
        let client = APIClient(
            baseURL: "https://api.example.com",
            session: session,
            tokenProvider: { nil }
        )
        return MarketDataService(api: client)
    }

    private static func stubStockInfoResponse() -> StockInfoResponse {
        StockInfoResponse(
            quote: StockQuoteResponse(
                symbol: "AAPL",
                name: "Apple Inc.",
                price: "184.20",
                change: "1.50",
                changePercent: "0.82",
                open: "183.00",
                dayHigh: "185.00",
                dayLow: "182.50",
                previousClose: "182.70",
                volume: 50_000_000,
                avgVolume: 60_000_000,
                marketCap: 3_000_000_000_000,
                peRatio: "30.0",
                eps: "6.10",
                yearHigh: "200.00",
                yearLow: "150.00",
                priceAvg50: "180.00",
                priceAvg200: "175.00",
                sharesOutstanding: 16_000_000_000,
                earningsAnnouncement: nil,
                timestamp: 1_714_320_000
            ),
            profile: StockProfileResponse(
                name: "Apple Inc.",
                sector: nil,
                industry: nil,
                description: nil,
                ceo: nil,
                website: nil,
                employees: nil,
                beta: nil,
                ipoDate: nil,
                exchange: "NASDAQ",
                logoUrl: nil
            ),
            ratios: StockRatiosResponse(
                dividendYield: nil,
                payoutRatio: nil,
                roe: nil,
                roa: nil,
                profitMargin: nil,
                operatingMargin: nil,
                grossMargin: nil,
                debtToEquity: nil,
                currentRatio: nil,
                priceToBook: nil,
                priceToSales: nil,
                evToEbitda: nil,
                freeCashFlowYield: nil,
                pegRatio: nil
            ),
            analyst: StockAnalystResponse(
                targetHigh: nil,
                targetLow: nil,
                targetConsensus: nil,
                targetMedian: nil,
                strongBuy: nil,
                buy: nil,
                hold: nil,
                sell: nil,
                strongSell: nil
            )
        )
    }
}
