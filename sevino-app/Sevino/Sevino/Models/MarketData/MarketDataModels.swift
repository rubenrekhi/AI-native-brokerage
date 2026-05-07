import Foundation

// MARK: - Stock Info (GET /v1/market-data/stocks/{symbol})

struct StockInfoResponse: Decodable {
    let quote: StockQuoteResponse
    let profile: StockProfileResponse
    let ratios: StockRatiosResponse
    let analyst: StockAnalystResponse
}

struct StockQuoteResponse: Decodable, Identifiable, Equatable {
    var id: String { symbol }
    let symbol: String
    let name: String
    let price: String
    let change: String
    let changePercent: String
    let open: String
    let dayHigh: String
    let dayLow: String
    let previousClose: String
    let volume: Int
    let avgVolume: Int
    let marketCap: Int
    let peRatio: String?
    let eps: String?
    let yearHigh: String
    let yearLow: String
    let priceAvg50: String
    let priceAvg200: String
    let sharesOutstanding: Int
    let earningsAnnouncement: String?
    /// Unix epoch seconds at which the quote was sourced upstream.
    let timestamp: Int

    // Convenience computed properties
    var priceValue: Decimal? { Decimal(string: price) }
    var changeValue: Decimal? { Decimal(string: change) }
    var isNegativeChange: Bool {
        guard let val = changeValue else { return false }
        return val < 0
    }
    var timestampDate: Date { Date(timeIntervalSince1970: TimeInterval(timestamp)) }
}

struct StockProfileResponse: Decodable, Equatable {
    let name: String
    let sector: String?
    let industry: String?
    let description: String?
    let ceo: String?
    let website: String?
    let employees: Int?
    let beta: String?
    let ipoDate: String?
    let exchange: String
    let logoUrl: String?
}

struct StockRatiosResponse: Decodable, Equatable {
    let dividendYield: String?
    let payoutRatio: String?
    let roe: String?
    let roa: String?
    let profitMargin: String?
    let operatingMargin: String?
    let grossMargin: String?
    let debtToEquity: String?
    let currentRatio: String?
    let priceToBook: String?
    let priceToSales: String?
    let evToEbitda: String?
    let freeCashFlowYield: String?
    let pegRatio: String?
}

struct StockAnalystResponse: Decodable, Equatable {
    let targetHigh: String?
    let targetLow: String?
    let targetConsensus: String?
    let targetMedian: String?
    let strongBuy: Int?
    let buy: Int?
    let hold: Int?
    let sell: Int?
    let strongSell: Int?
}

// MARK: - Batch Quotes (GET /v1/market-data/stocks/batch)

struct BatchQuoteResponse: Decodable {
    let quotes: [StockQuoteResponse]
}

// MARK: - Chart (GET /v1/market-data/stocks/{symbol}/chart)

enum ChartTimeframe: String, CaseIterable, Identifiable {
    case oneDay = "1D"
    case oneWeek = "1W"
    case oneMonth = "1M"
    case threeMonths = "3M"
    case sixMonths = "6M"
    case oneYear = "1Y"
    case fiveYears = "5Y"

    var id: String { rawValue }

    var displayLabel: String {
        switch self {
        case .oneDay: "1D"
        case .oneWeek: "1W"
        case .oneMonth: "1M"
        case .threeMonths: "3M"
        case .sixMonths: "6M"
        case .oneYear: "1Y"
        case .fiveYears: "5Y"
        }
    }
}

struct ChartResponse: Decodable {
    let symbol: String
    let timeframe: String
    let bars: [PriceBar]
}

struct PriceBar: Decodable, Identifiable, Equatable {
    var id: String { timestamp }
    /// ISO8601 timestamp string, as returned by the backend.
    let timestamp: String
    let open: String
    let high: String
    let low: String
    let close: String
    let volume: Int
    let vwap: String
    let tradeCount: Int

    var closeValue: Decimal? { Decimal(string: close) }
}

// MARK: - Market Status (GET /v1/market-data/market/status)

struct MarketStatusResponse: Decodable {
    let isOpen: Bool
    let nextOpen: String
    let nextClose: String
    /// ISO8601 timestamp string, as returned by the backend.
    let timestamp: String
}
