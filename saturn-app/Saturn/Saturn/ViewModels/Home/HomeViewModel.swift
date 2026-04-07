import Foundation

@Observable
final class HomeViewModel {
    private(set) var greeting = ""
    private(set) var portfolioDisplayValue = "$1,084.92"
    private(set) var portfolioIsDown = true

    func loadGreeting() {
        let hour = Calendar.current.component(.hour, from: Date.now)
        let name = "Riley"
        switch hour {
        case 5..<12: greeting = L10n.Home.greetingMorning(name)
        case 12..<17: greeting = L10n.Home.greetingAfternoon(name)
        default: greeting = L10n.Home.greetingEvening(name)
        }
    }
}
