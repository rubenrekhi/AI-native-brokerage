import Foundation

enum HoldingsDisplayOption: CaseIterable, Identifiable {
    case allTimeReturn, todaysReturn, totalValue, priceChange

    var id: Self { self }

    var label: String {
        switch self {
        case .allTimeReturn: L10n.Home.filterAllTimeReturn
        case .todaysReturn: L10n.Home.filterTodaysReturn
        case .totalValue: L10n.Home.filterTotalValue
        case .priceChange: L10n.Home.filterPriceChange
        }
    }
}
