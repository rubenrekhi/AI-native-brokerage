import SwiftUI

extension Color {
    /// Frosted card surface on the digest's coloured gradient. Intentionally
    /// light in both schemes — the story card floats on a fixed
    /// lavender/peach/sky gradient, so it does not adapt to dark mode.
    static let digestCardSurface = Color.white.opacity(0.88)
    static let digestCardBorder = Color.white.opacity(0.65)
    static let digestCloseButtonBackground = Color.white.opacity(0.70)
}
