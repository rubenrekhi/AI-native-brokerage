import Foundation

/// Protocol for the market-data endpoints — quote, profile/ratios/analyst,
/// batch quotes, charts, and market status. Used by ticker-mention previews
/// and the stock-detail screen; protocol enables mocking in previews/tests.
protocol MarketDataServiceProtocol: Sendable {
    func getStockInfo(symbol: String) async throws -> StockInfoResponse
    func getBatchQuotes(symbols: [String]) async throws -> BatchQuoteResponse
    func getChart(symbol: String, timeframe: ChartTimeframe) async throws -> ChartResponse
    func getMarketStatus() async throws -> MarketStatusResponse
}

/// Calls the `/v1/market-data/*` endpoints on the Sevino API.
final class MarketDataService: MarketDataServiceProtocol {
    static let shared = MarketDataService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func getStockInfo(symbol: String) async throws -> StockInfoResponse {
        try await api.get("/v1/market-data/stocks/\(symbol)")
    }

    func getBatchQuotes(symbols: [String]) async throws -> BatchQuoteResponse {
        var components = URLComponents()
        components.path = "/v1/market-data/stocks/batch"
        components.queryItems = [
            URLQueryItem(name: "symbols", value: symbols.joined(separator: ",")),
        ]
        guard let path = components.string else {
            throw URLError(.badURL)
        }
        return try await api.get(path)
    }

    func getChart(symbol: String, timeframe: ChartTimeframe) async throws -> ChartResponse {
        var components = URLComponents()
        components.path = "/v1/market-data/stocks/\(symbol)/chart"
        components.queryItems = [
            URLQueryItem(name: "timeframe", value: timeframe.rawValue),
        ]
        guard let path = components.string else {
            throw URLError(.badURL)
        }
        return try await api.get(path)
    }

    func getMarketStatus() async throws -> MarketStatusResponse {
        try await api.get("/v1/market-data/market/status")
    }
}
