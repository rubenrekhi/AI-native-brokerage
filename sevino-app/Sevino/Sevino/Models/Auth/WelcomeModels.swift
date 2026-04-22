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
