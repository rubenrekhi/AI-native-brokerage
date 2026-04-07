import SwiftUI

extension Color {
    /// Send button active circle — uses the opposite mode's accent
    /// Light mode: dark accent #29243B, Dark mode: light accent #CCBEFF
    static let homeSendActiveBg = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.80, green: 0.75, blue: 1.00, alpha: 1)  // #CCBEFF
            : UIColor(red: 0.16, green: 0.14, blue: 0.23, alpha: 1)  // #29243B
    })
}
