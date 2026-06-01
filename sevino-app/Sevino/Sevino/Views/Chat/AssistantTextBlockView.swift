import SwiftUI
import MarkdownUI

struct AssistantTextBlockView: View {
    let block: TextBlock
    let isStreaming: Bool
    let scale: CGFloat
    let ordinal: Int
    let hasLaterTextBlock: Bool
    let sequencer: MessageTypewriterSequencer

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var displayedText = ""

    private var isGated: Bool {
        isStreaming && !sequencer.isUnlocked(ordinal: ordinal)
    }

    // Marking completed is only safe once no more deltas can arrive — otherwise
    // the typewriter catches up mid-stream and unlocks the next block early.
    private var isStreamSettled: Bool {
        !isStreaming || hasLaterTextBlock
    }

    var body: some View {
        Markdown(renderedText)
            .markdownTheme(.sevino(scale: scale))
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16 * scale)
            .opacity(isGated ? 0 : 1)
            .task(id: typewriterTaskId) {
                guard !isGated else { return }
                guard isStreaming, !reduceMotion else {
                    displayedText = block.text
                    sequencer.markCompleted(ordinal: ordinal)
                    return
                }
                while !Task.isCancelled {
                    let next = TypewriterStreamingBuffer.advance(
                        from: displayedText,
                        toward: block.text
                    )
                    if next == block.text {
                        displayedText = block.text
                        if isStreamSettled {
                            sequencer.markCompleted(ordinal: ordinal)
                        }
                        break
                    }
                    displayedText = next
                    try? await Task.sleep(for: TypewriterAnimation.defaultSpeed)
                }
            }
            .onChange(of: isStreaming) { _, streaming in
                if !streaming {
                    displayedText = block.text
                    sequencer.markCompleted(ordinal: ordinal)
                }
            }
    }

    private var renderedText: String {
        if !isStreaming || reduceMotion {
            return block.text
        }
        return displayedText.isEmpty ? "" : displayedText
    }

    // `isStreamSettled` is part of the key so a caught-up typewriter re-runs
    // (and marks completed) when a later block finally arrives.
    private var typewriterTaskId: String {
        "\(isGated)|\(isStreamSettled)|\(block.text)"
    }
}

#Preview("Static") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        AssistantTextBlockView(
            block: TextBlock(
                blockId: "1",
                text: """
                Here is **bold** and *italic* text.

                ### Heading

                | Symbol | Company | Price | Day Change | Market Cap |
                |---|---|---|---|---|
                | AAPL | Apple Inc. | $189.45 | +1.23% | $2.95T |
                | MSFT | Microsoft Corporation | $412.80 | -0.45% | $3.07T |
                | NVDA | NVIDIA Corporation | $1,024.30 | +3.10% | $2.52T |
                """
            ),
            isStreaming: false,
            scale: 1,
            ordinal: 0,
            hasLaterTextBlock: false,
            sequencer: MessageTypewriterSequencer()
        )
    }
    .preferredColorScheme(.dark)
}
