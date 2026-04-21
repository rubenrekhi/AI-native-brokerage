import Foundation

enum WelcomePageKind: CaseIterable, Identifiable {
    case portfolio, trade, research, protected

    var id: Self { self }
}

struct WelcomePage: Identifiable {
    var id: WelcomePageKind { kind }
    let kind: WelcomePageKind
    let title: String
    let subtitle: String
    let backgroundImage: String
}

enum Timeframe: String, CaseIterable, Identifiable {
    case oneDay = "1D"
    case oneWeek = "1W"
    case oneMonth = "1M"
    case threeMonths = "3M"
    case sixMonths = "6M"
    case ytd = "YTD"
    case oneYear = "1Y"
    case all = "ALL"

    var id: String { rawValue }

    var displayTitle: String {
        switch self {
        case .oneDay: L10n.Welcome.timeframe1D
        case .oneWeek: L10n.Welcome.timeframe1W
        case .oneMonth: L10n.Welcome.timeframe1M
        case .threeMonths: L10n.Welcome.timeframe3M
        case .sixMonths: L10n.Welcome.timeframe6M
        case .ytd: L10n.Welcome.timeframeYTD
        case .oneYear: L10n.Welcome.timeframe1Y
        case .all: L10n.Welcome.timeframeAll
        }
    }
}
