import Foundation

struct Holding: Identifiable {
    var id: String { ticker }
    let ticker: String
    let isCash: Bool
    let shares: String?
    let value: String
    let gainLossText: String?
    let isPositive: Bool?
    let daysGain: String?
    let daysGainPercent: String?
    let totalGain: String?
    let totalGainPercent: String?
    let averageCost: String?
}
