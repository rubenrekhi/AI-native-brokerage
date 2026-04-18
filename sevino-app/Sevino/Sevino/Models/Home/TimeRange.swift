import Foundation

enum TimeRange: String, CaseIterable, Identifiable {
    case oneDay = "1D"
    case oneWeek = "1W"
    case oneMonth = "1M"
    case threeMonths = "3M"
    case sixMonths = "6M"
    case ytd = "YTD"
    case oneYear = "1Y"
    case all = "ALL"

    var id: Self { self }

    var periodLabel: String {
        switch self {
        case .oneDay: L10n.Home.periodToday
        case .oneWeek: L10n.Home.period7Days
        case .oneMonth: L10n.Home.period30Days
        case .threeMonths: L10n.Home.period3Months
        case .sixMonths: L10n.Home.period6Months
        case .ytd: L10n.Home.periodYtd
        case .oneYear: L10n.Home.periodYear
        case .all: L10n.Home.periodAllTime
        }
    }
}
