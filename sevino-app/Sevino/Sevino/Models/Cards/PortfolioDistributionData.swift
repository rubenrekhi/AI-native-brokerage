import Foundation
import SwiftUI

struct PortfolioDistributionData: Codable, Equatable {
    let totalValue: Decimal
    let currencyCode: String
    let segments: [DistributionSegment]
}

struct DistributionSegment: Codable, Equatable, Identifiable {
    let id: String
    let label: String
    let fraction: Double
    let amount: Decimal
    let colorToken: DistributionSegmentColor
}

enum DistributionSegmentColor: String, Codable, Equatable {
    case info
    case positive
    case warning
    case avatarPurple = "avatar_purple"
    case greyContrast = "grey_contrast"

    var color: Color {
        switch self {
        case .info: .sevinoInfo
        case .positive: .sevinoPositive
        case .warning: .sevinoWarning
        case .avatarPurple: .sevinoAvatarPurple
        case .greyContrast: .sevinoGreyContrast
        }
    }
}
