import Foundation

struct RadarItem: Identifiable {
    var id: String { ticker }
    let ticker: String
    let description: String
    let price: String
    let changePercent: String
    let isPositive: Bool
    let expiresIn: String
    var isStarred: Bool
}
