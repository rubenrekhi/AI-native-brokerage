import Foundation

/// Protocol for fetching radar watchlist recommendations — enables mocking in previews and tests.
protocol RadarServiceProtocol {
    func fetchRadar() async throws -> [RadarItem]
}

/// Placeholder implementation that returns canned radar items. This is the default
/// service used by `RadarViewModel` until the backend endpoint exists — it is
/// not a test double.
final class PlaceholderRadarService: RadarServiceProtocol {
    static let shared = PlaceholderRadarService()

    func fetchRadar() async throws -> [RadarItem] {
        [
            RadarItem(
                ticker: "TSLA",
                description: "Automotive tech leader you asked about last week, earnings in 2 days.",
                price: "$274.63", changePercent: "+1.24%", isPositive: true,
                expiresIn: "6 days", isStarred: false
            ),
            RadarItem(
                ticker: "NVDA",
                description: "AI chip giant with record data center revenue, up 180% this year.",
                price: "$892.41", changePercent: "+2.67%", isPositive: true,
                expiresIn: "3 days", isStarred: false
            ),
            RadarItem(
                ticker: "AAPL",
                description: "iPhone maker nearing $4T market cap, services revenue accelerating.",
                price: "$198.11", changePercent: "-0.43%", isPositive: false,
                expiresIn: "5 days", isStarred: true
            ),
            RadarItem(
                ticker: "AMZN",
                description: "Cloud and retail leader with AWS growth reaccelerating to 19%.",
                price: "$186.49", changePercent: "+0.91%", isPositive: true,
                expiresIn: "4 days", isStarred: false
            ),
        ]
    }
}
