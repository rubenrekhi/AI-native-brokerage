import SwiftUI

/// Card-local palette for the transfer flow. Adapts to light/dark via the app's
/// `Color.adaptive` / `sevinoSecondary` tokens so text and accents read correctly
/// in both modes — the card surface itself comes from the shared
/// `GenUICardBackground`. The saturated mint/amber/red accents are deepened in
/// light mode for contrast on a white card and stay bright in dark mode. Shared
/// between `TransferCard` and `TransferConfirmationCard`.
enum TransferPalette {
    // Inner surfaces (chips sit on top of the GenUICardBackground card surface)
    static let chipBackground = Color.sevinoSecondary.opacity(0.05)
    static let chipBorder = Color.sevinoSecondary.opacity(0.08)

    // Direction accents — bright in dark, deepened in light for white-card contrast
    static let depositGreen = Color.adaptive(light: 0x1E8A60, dark: 0x7AE88F)
    static let depositGreenMuted = Color.adaptive(light: 0x1E8A60, dark: 0x7AE88F).opacity(0.16)
    static let withdrawAmber = Color.adaptive(light: 0xB7791F, dark: 0xEDB54A)
    static let withdrawAmberMuted = Color.adaptive(light: 0xB7791F, dark: 0xEDB54A).opacity(0.16)
    static let failRed = Color.adaptive(light: 0xC0392B, dark: 0xED5757)
    static let failRedMuted = Color.adaptive(light: 0xC0392B, dark: 0xED5757).opacity(0.16)

    // Confirm button (manual entry flow only — the AI card uses HoldToConfirmButton)
    static let confirmEnabled = Color.adaptive(light: 0x1E8A60, dark: 0xA8F08C)
    static let confirmEnabledText = Color.adaptive(light: 0xFFFFFF, dark: 0x000000)
    static let confirmDisabledBg = Color.sevinoSecondary.opacity(0.08)
    static let confirmDisabledText = Color.sevinoSecondary.opacity(0.4)

    // Text & strokes — sevinoSecondary is near-black in light, near-white in dark
    static let textPrimary = Color.sevinoSecondary
    static let textSecondary = Color.sevinoSecondary.opacity(0.6)
    static let textTertiary = Color.sevinoSecondary.opacity(0.5)
    static let textMuted = Color.sevinoSecondary.opacity(0.45)
    static let textFaint = Color.sevinoSecondary.opacity(0.4)
    static let iconBgSubtle = Color.sevinoSecondary.opacity(0.08)
    static let iconBgHairline = Color.sevinoSecondary.opacity(0.06)
    static let hairline = Color.sevinoSecondary.opacity(0.1)
    static let dividerSubtle = Color.sevinoSecondary.opacity(0.08)
}
