import Foundation

@Observable
final class HomeViewModel {
    private(set) var greeting = ""
    private(set) var portfolioDisplayValue = "$1,084.92"
    private(set) var portfolioIsDown = true
    private(set) var portfolioGainText = "+232.82 (+27.64%)"
    private(set) var portfolioChartPoints: [CGFloat] = []
    private(set) var selectedTimeRange = TimeRange.oneMonth

    // MARK: - Funding mock data
    private(set) var cashBalance = "$2,412.08"
    private(set) var cashApy = "3.20%"
    private(set) var cashThisMonth = "+$6.43"
    private(set) var cashDaysAccrued = "22"
    private(set) var cashLifetime = "+$41.87"
    private(set) var cashLifetimeSince = "Oct 2025"
    private(set) var cashBuyingPower = "$2,412.08"
    private(set) var cashPendingDeposits = "$100.50"
    private(set) var cashInterestPaidOut = "Monthly"
    private(set) var cashFdicInsured = "$2,500,000"

    // MARK: - Holdings mock data
    private(set) var holdings: [Holding] = []

    // MARK: - Radar mock data
    private(set) var radarItems: [RadarItem] = []

    // MARK: - Funding (real state)
    let funding = FundingViewModel()

    func loadGreeting() {
        let hour = Calendar.current.component(.hour, from: Date.now)
        let name = "Riley"
        switch hour {
        case 5..<12: greeting = L10n.Home.greetingMorning(name)
        case 12..<17: greeting = L10n.Home.greetingAfternoon(name)
        default: greeting = L10n.Home.greetingEvening(name)
        }
        loadMockChartData()
        loadMockHoldings()
        loadMockRadar()
    }

    func toggleRadarStar(id: String) {
        guard let idx = radarItems.firstIndex(where: { $0.id == id }) else { return }
        radarItems[idx].isStarred.toggle()
    }

    func selectTimeRange(_ range: TimeRange) {
        selectedTimeRange = range
        loadMockChartData()
    }

    var portfolioPeriodLabel: String {
        selectedTimeRange.periodLabel
    }

    private func loadMockHoldings() {
        holdings = [
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

    private func loadMockChartData() {
        var points: [CGFloat] = []
        var value: CGFloat = 0.15
        for _ in 0..<40 {
            value += CGFloat.random(in: -0.03...0.05)
            value = max(0.05, min(1.0, value))
            points.append(value)
        }
        points[points.count - 1] = 0.92
        points[points.count - 2] = 0.88
        points[points.count - 3] = 0.95
        portfolioChartPoints = points
    }

    private func loadMockRadar() {
        radarItems = [
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
