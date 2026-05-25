import SwiftUI

/// Shared background for user message bubbles and gen-UI cards in the chat.
struct ChatBubbleBackground: View {
    @Environment(\.colorScheme) private var colorScheme
    var cornerRadius: CGFloat = 20

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(Color.chatBubbleFill)
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius)
                    .stroke(
                        Color.chatBubbleBorder
                            .opacity(colorScheme == .dark ? 0.12 : 0.08),
                        lineWidth: 1
                    )
            }
    }
}

/// Alias so gen-UI cards share the same background as user bubbles.
typealias GenUICardBackground = ChatBubbleBackground

#Preview("Chat Bubble Background") {
    VStack(spacing: 20) {
        ChatBubbleBackground()
            .frame(width: 200, height: 60)
        GenUICardBackground(cornerRadius: 12)
            .frame(width: 200, height: 100)
    }
    .padding()
}
