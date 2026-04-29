import Foundation

struct SingleStockCardData: Codable, Equatable {
    let ticker: String
    let companyName: String
    let price: String
    let gainLossText: String
    let isPositive: Bool
    let periodLabel: String
    let chartPoints: [Double]
    let selectedTimeRange: TimeRange
    let stats: StockStats?
}

struct StockStats: Codable, Equatable {
    let bid: String
    let ask: String
    let lastSale: String
    let open: String
    let high: String
    let low: String
    let exchange: String
    let marketCap: String
    let peRatio: String
    let fiftyTwoWeekHigh: String
    let fiftyTwoWeekLow: String
    let volume: String
    let avgVolume: String
    let marginReq: String
}
