import SwiftUI
import MarkdownUI

struct AssistantTextBlockView: View {
    let block: TextBlock
    let isStreaming: Bool
    let scale: CGFloat

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var displayedText = ""

    var body: some View {
        Markdown(renderedText)
            .markdownTheme(.sevino(scale: scale))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16 * scale)
            .task(id: block.text) {
                guard isStreaming, !reduceMotion else {
                    displayedText = block.text
                    return
                }
                while !Task.isCancelled {
                    let next = TypewriterStreamingBuffer.advance(
                        from: displayedText,
                        toward: block.text
                    )
                    if next == block.text {
                        displayedText = block.text
                        break
                    }
                    displayedText = next
                    try? await Task.sleep(for: TypewriterAnimation.defaultSpeed)
                }
            }
            .onChange(of: isStreaming) { _, streaming in
                if !streaming {
                    displayedText = block.text
                }
            }
    }

    private var renderedText: String {
        if !isStreaming || reduceMotion {
            return block.text
        }
        return displayedText.isEmpty ? block.text : displayedText
    }
}

#Preview("Static") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        AssistantTextBlockView(
            block: TextBlock(
                blockId: "1",
                text: "Here is **bold** and *italic* text.\n\n### Heading\n\n| Col A | Col B |\n|---|---|\n| 1 | 2 |"
            ),
            isStreaming: false,
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}
