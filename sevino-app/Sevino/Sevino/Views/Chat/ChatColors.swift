import SwiftUI

extension Color {
    /// Chat bubble fill — light: #FFFFFF, dark: #000000
    static let chatBubbleFill = adaptive(light: 0xFFFFFF, dark: 0x000000)

    /// Chat bubble border — light: #000000, dark: #FFFFFF (apply opacity at use site)
    static let chatBubbleBorder = adaptive(light: 0x000000, dark: 0xFFFFFF)
}
