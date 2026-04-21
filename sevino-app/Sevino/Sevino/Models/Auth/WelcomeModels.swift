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
}
