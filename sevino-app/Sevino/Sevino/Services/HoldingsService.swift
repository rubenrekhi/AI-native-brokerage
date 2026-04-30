import Foundation

/// Protocol for fetching holdings data — enables mocking in previews and tests.
protocol HoldingsServiceProtocol {
    func fetchHoldings() async throws -> [Holding]
}

/// Placeholder implementation that returns canned holdings. This is the default
/// service used by `HoldingsViewModel` until the backend endpoint exists — it is
/// not a test double.
final class PlaceholderHoldingsService: HoldingsServiceProtocol {
    static let shared = PlaceholderHoldingsService()

    func fetchHoldings() async throws -> [Holding] {
        [
            Holding(
                ticker: "CASH", isCash: true,
                shares: nil, value: "$40,291.92", gainLossText: nil, isPositive: nil,
                daysGain: nil, daysGainPercent: nil, totalGain: nil, totalGainPercent: nil, averageCost: nil
            ),
            Holding(
                ticker: "TSLA", isCash: false,
                shares: "57", value: "$21,748.18",
                gainLossText: "+$7,418.90 (+51.74%)", isPositive: true,
                daysGain: "+734.73", daysGainPercent: "+3.50%",
                totalGain: "+$7,418.90", totalGainPercent: "+51.74%",
                averageCost: "$248.91"
            ),
            Holding(
                ticker: "AMD", isCash: false,
                shares: "37", value: "$11,465.19",
                gainLossText: "-$1,049.32 (-8.38%)", isPositive: false,
                daysGain: "-89.21", daysGainPercent: "-0.77%",
                totalGain: "-$1,049.32", totalGainPercent: "-8.38%",
                averageCost: "$338.23"
            ),
        ]
    }
}
