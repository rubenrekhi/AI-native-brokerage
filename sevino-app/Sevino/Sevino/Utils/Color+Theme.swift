import SwiftUI

extension Color {
    /// Primary background — light: #FDFDFD, dark: #000000
    static let sevinoPrimary = adaptive(light: 0xFDFDFD, dark: 0x000000)

    /// Primary text — light: #121111, dark: #F9F8F6
    static let sevinoSecondary = adaptive(light: 0x121111, dark: 0xF9F8F6)

    /// Gradient accent — light: #CCBEFF, dark: #29243B
    static let sevinoAccent = adaptive(light: 0xCCBEFF, dark: 0x29243B)

    /// Dark/light grey for text — light: #1E1E1E, dark: #ABABAB
    static let sevinoGreyContrast = adaptive(light: 0x1E1E1E, dark: 0xABABAB)

    /// Inactive/outlines — light: #BFBFBF, dark: #312E2E
    static let sevinoGreyAccent = adaptive(light: 0xBFBFBF, dark: 0x312E2E)

    /// Settings/text background — light: #F5F4ED, dark: #040404
    static let sevinoSettingsBg = adaptive(light: 0xF5F4ED, dark: 0x040404)

    /// Settings contrast — light: #FFFFFF, dark: #121111
    static let sevinoSettingsContrast = adaptive(light: 0xFFFFFF, dark: 0x121111)

    /// Positive/green — #1E8A60 (same in both modes)
    static let sevinoPositive = adaptive(light: 0x1E8A60, dark: 0x1E8A60)

    /// Negative/red — #991C1E (same in both modes)
    static let sevinoNegative = adaptive(light: 0x991C1E, dark: 0x991C1E)

    /// Info/in-progress blue — #2D7FF9 (same in both modes)
    static let sevinoInfo = adaptive(light: 0x2D7FF9, dark: 0x2D7FF9)

    /// Avatar gradient start — #AF52DE (same in both modes)
    static let sevinoAvatarPurple = adaptive(light: 0xAF52DE, dark: 0xAF52DE)

    /// Warning/action-required orange — #E08A00 (same in both modes)
    static let sevinoWarning = adaptive(light: 0xE08A00, dark: 0xE08A00)

    /// Selection highlight background — light: #C9DAF0, dark: #0F203A
    static let sevinoHighlightBg = adaptive(light: 0xC9DAF0, dark: 0x0F203A)

    /// Selection highlight text — #0088FF (same in both modes)
    static let sevinoHighlightText = adaptive(light: 0x0088FF, dark: 0x0088FF)

    /// Drop shadow base — #000000 (same in both modes; apply opacity at use site)
    static let sevinoShadow = adaptive(light: 0x000000, dark: 0x000000)

    static let sevinoGradientLavender = Color(red: 0.80, green: 0.75, blue: 1.0)
    static let sevinoGradientPeach    = Color(red: 1.0,  green: 0.82, blue: 0.75)
    static let sevinoGradientMint     = Color(red: 0.70, green: 0.95, blue: 0.88)
    static let sevinoGradientSky      = Color(red: 0.73, green: 0.85, blue: 1.0)
    static let sevinoGradientRose     = Color(red: 1.0,  green: 0.78, blue: 0.84)

    static func adaptive(light: UInt, dark: UInt) -> Color {
        Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(hex: dark)
                : UIColor(hex: light)
        })
    }
}

private extension UIColor {
    convenience init(hex: UInt) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255.0,
            green: CGFloat((hex >> 8) & 0xFF) / 255.0,
            blue: CGFloat(hex & 0xFF) / 255.0,
            alpha: 1.0
        )
    }
}
