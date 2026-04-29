import SwiftUI

/// Card-local palette for the transfer flow. Saturated mint/amber/red tints that
/// don't exist in the global theme (Sevino is pre-launch, so these live here until a
/// shared "MCP card" palette is extracted). Shared between `TransferCard` and
/// `TransferConfirmationCard`.
enum TransferPalette {
    // Surfaces
    static let cardBackground = Color(red: 0.09, green: 0.09, blue: 0.10)
    static let chipBackground = Color.white.opacity(0.04)
    static let chipBorder = Color.white.opacity(0.06)

    // Direction accents
    static let depositGreen = Color(red: 0.48, green: 0.91, blue: 0.56)
    static let depositGreenMuted = Color(red: 0.48, green: 0.91, blue: 0.56).opacity(0.14)
    static let withdrawAmber = Color(red: 0.93, green: 0.71, blue: 0.29)
    static let withdrawAmberMuted = Color(red: 0.93, green: 0.71, blue: 0.29).opacity(0.14)
    static let failRed = Color(red: 0.93, green: 0.34, blue: 0.34)
    static let failRedMuted = Color(red: 0.93, green: 0.34, blue: 0.34).opacity(0.14)

    // Confirm button
    static let confirmEnabled = Color(red: 0.66, green: 0.94, blue: 0.55)
    static let confirmEnabledText = Color.black
    static let confirmDisabledBg = Color.white.opacity(0.06)
    static let confirmDisabledText = Color.white.opacity(0.45)

    // Semantic text & stroke tokens (used across both card files)
    static let textPrimary = Color.white
    static let textSecondary = Color.white.opacity(0.55)
    static let textTertiary = Color.white.opacity(0.5)
    static let textMuted = Color.white.opacity(0.45)
    static let textFaint = Color.white.opacity(0.4)
    static let iconBgSubtle = Color.white.opacity(0.08)
    static let iconBgHairline = Color.white.opacity(0.06)
    static let hairline = Color.white.opacity(0.06)
    static let dividerSubtle = Color.white.opacity(0.05)
}
