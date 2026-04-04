import SwiftUI

extension Color {
    /// Primary background — light: #F9F8F6, dark: #000000
    static let saturnPrimary = adaptive(light: 0xF9F8F6, dark: 0x000000)

    /// Primary text — light: #121111, dark: #F9F8F6
    static let saturnSecondary = adaptive(light: 0x121111, dark: 0xF9F8F6)

    /// Gradient accent — light: #CCBEFF, dark: #29243B
    static let saturnAccent = adaptive(light: 0xCCBEFF, dark: 0x29243B)

    /// Dark/light grey for text — light: #1E1E1E, dark: #ABABAB
    static let saturnGreyContrast = adaptive(light: 0x1E1E1E, dark: 0xABABAB)

    /// Inactive/outlines — light: #BFBFBF, dark: #312E2E
    static let saturnGreyAccent = adaptive(light: 0xBFBFBF, dark: 0x312E2E)

    /// Settings/text background — light: #F5F4ED, dark: #040404
    static let saturnSettingsBg = adaptive(light: 0xF5F4ED, dark: 0x040404)

    /// Settings contrast — light: #FFFFFF, dark: #121111
    static let saturnSettingsContrast = adaptive(light: 0xFFFFFF, dark: 0x121111)

    /// Positive/green — #1E8A60 (same in both modes)
    static let saturnPositive = adaptive(light: 0x1E8A60, dark: 0x1E8A60)

    /// Negative/red — #991C1E (same in both modes)
    static let saturnNegative = adaptive(light: 0x991C1E, dark: 0x991C1E)

    /// Selection highlight background — #C9DAF0 (same in both modes)
    static let saturnHighlightBg = adaptive(light: 0xC9DAF0, dark: 0xC9DAF0)

    /// Selection highlight text — #0088FF (same in both modes)
    static let saturnHighlightText = adaptive(light: 0x0088FF, dark: 0x0088FF)

    private static func adaptive(light: UInt, dark: UInt) -> Color {
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
