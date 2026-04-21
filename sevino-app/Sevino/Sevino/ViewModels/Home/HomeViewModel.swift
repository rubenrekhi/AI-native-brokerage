import Foundation

@Observable
final class HomeViewModel {
    private(set) var greeting = ""

    // MARK: - Holdings mock data
    private(set) var holdings: [Holding] = []

    // MARK: - Radar mock data
    private(set) var radarItems: [RadarItem] = []

    // MARK: - Sidebar mock chats
    // TODO: Replace with real chat history from backend
    private(set) var mockChats = [
        ChatItem(title: "How was Tesla's most recent e..."),
        ChatItem(title: "Help me balance my portfolio"),
        ChatItem(title: "What happened with AMD this..."),
        ChatItem(title: "What is an option?"),
        ChatItem(title: "How much would I have made ..."),
    ]

    // MARK: - Contact URLs

    func founderPhoneURL() -> URL? { URL(string: "tel:4169189713") }
    func founderTextURL() -> URL? { URL(string: "sms:4169189713") }
    func contactEmailURL() -> URL? { URL(string: "mailto:admin@sevino.ai") }

    func loadGreeting() {
        let hour = Calendar.current.component(.hour, from: Date.now)
        let name = "Riley"
        switch hour {
        case 5..<12: greeting = L10n.Home.greetingMorning(name)
        case 12..<17: greeting = L10n.Home.greetingAfternoon(name)
        default: greeting = L10n.Home.greetingEvening(name)
        }
        loadMockHoldings()
        loadMockRadar()
    }

    func toggleRadarStar(id: String) {
        guard let idx = radarItems.firstIndex(where: { $0.id == id }) else { return }
        radarItems[idx].isStarred.toggle()
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
