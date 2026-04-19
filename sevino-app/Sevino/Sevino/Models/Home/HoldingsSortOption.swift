import Foundation

enum HoldingsSortOption: CaseIterable, Identifiable {
    case highToLow, lowToHigh, alphabetical

    var id: Self { self }

    var label: String {
        switch self {
        case .highToLow: L10n.Home.filterHighToLow
        case .lowToHigh: L10n.Home.filterLowToHigh
        case .alphabetical: L10n.Home.filterAlphabetical
        }
    }
}
