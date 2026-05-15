import SwiftUI

/// Shared background for user message bubbles and gen-UI cards in the chat.
struct ChatBubbleBackground: View {
    @Environment(\.colorScheme) private var colorScheme
    var cornerRadius: CGFloat = 20

    private var fillColor: Color {
        colorScheme == .dark ? .sevinoGreyAccent : .sevinoSettingsBg
    }

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(fillColor)
    }
}

/// Alias so gen-UI cards share the same background as user bubbles.
typealias GenUICardBackground = ChatBubbleBackground
