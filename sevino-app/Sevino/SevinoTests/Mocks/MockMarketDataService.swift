import Foundation
@testable import Sevino

final class MockMarketDataService: MarketDataServiceProtocol, @unchecked Sendable {

    // Stubs
    var stockInfoResult: Result<StockInfoResponse, Error> = .failure(NotStubbedError())
    var batchQuotesResult: Result<BatchQuoteResponse, Error> = .failure(NotStubbedError())
    var chartResult: Result<ChartResponse, Error> = .failure(NotStubbedError())
    var marketStatusResult: Result<MarketStatusResponse, Error> = .failure(NotStubbedError())

    // Call tracking
    private(set) var stockInfoCalls: [String] = []
    private(set) var batchQuotesCalls: [[String]] = []
    private(set) var chartCalls: [ChartCall] = []
    private(set) var marketStatusCalls = 0

    struct NotStubbedError: Error {}

    struct ChartCall: Equatable {
        let symbol: String
        let timeframe: ChartTimeframe
    }

    func getStockInfo(symbol: String) async throws -> StockInfoResponse {
        stockInfoCalls.append(symbol)
        return try stockInfoResult.get()
    }

    func getBatchQuotes(symbols: [String]) async throws -> BatchQuoteResponse {
        batchQuotesCalls.append(symbols)
        return try batchQuotesResult.get()
    }

    func getChart(symbol: String, timeframe: ChartTimeframe) async throws -> ChartResponse {
        chartCalls.append(ChartCall(symbol: symbol, timeframe: timeframe))
        return try chartResult.get()
    }

    func getMarketStatus() async throws -> MarketStatusResponse {
        marketStatusCalls += 1
        return try marketStatusResult.get()
    }
}
