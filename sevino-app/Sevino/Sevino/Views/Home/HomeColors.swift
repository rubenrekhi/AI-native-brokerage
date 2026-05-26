import SwiftUI

extension Color {
    /// Star/favourite yellow — #FFD60A
    static let homeStarActive = Color(red: 1.0, green: 0.84, blue: 0.04)

    /// Lighter than sevinoGreyAccent in dark mode (#5A5757 vs #312E2E) for
    /// placeholder legibility on glass surfaces.
    static let homePlaceholder = adaptive(light: 0xBFBFBF, dark: 0x5A5757)

    static let homePopupDivider = Color.sevinoGreyAccent.opacity(0.3)
    static let homeDragHandle = Color.sevinoGreyContrast.opacity(0.5)

}
