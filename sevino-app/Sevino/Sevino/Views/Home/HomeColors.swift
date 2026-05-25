import SwiftUI

extension Color {
    /// Send button active circle — uses the opposite mode's accent
    /// Light mode: dark accent #29243B, Dark mode: light accent #CCBEFF
    static let homeSendActiveBg = Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 0.80, green: 0.75, blue: 1.00, alpha: 1)  // #CCBEFF
            : UIColor(red: 0.16, green: 0.14, blue: 0.23, alpha: 1)  // #29243B
    })

    /// Star/favourite yellow — #FFD60A
    static let homeStarActive = Color(red: 1.0, green: 0.84, blue: 0.04)

    static let homePopupDivider = Color.sevinoGreyAccent.opacity(0.3)
    static let homeDragHandle = Color.sevinoGreyContrast.opacity(0.5)

    // Gradient pastels for HomeBackgroundView mesh
    static let homeGradientLavender = Color(red: 0.80, green: 0.75, blue: 1.0)
    static let homeGradientPeach    = Color(red: 1.0,  green: 0.82, blue: 0.75)
    static let homeGradientMint     = Color(red: 0.70, green: 0.95, blue: 0.88)
    static let homeGradientSky      = Color(red: 0.73, green: 0.85, blue: 1.0)
    static let homeGradientRose     = Color(red: 1.0,  green: 0.78, blue: 0.84)
}
