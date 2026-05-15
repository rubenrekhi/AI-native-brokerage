import SwiftUI

struct MessageRowView: View {
    let message: Message
    let isLastAssistantMessage: Bool
    let turnState: ConversationStore.TurnState
    let scale: CGFloat

    private var isStreamingText: Bool {
        isLastAssistantMessage && turnState == .streaming
    }

    var body: some View {
        switch message.role {
        case .user:
            userRow
        case .assistant:
            assistantRow
        }
    }

    @ViewBuilder
    private var userRow: some View {
        let text = message.blocks.compactMap { block -> String? in
            if case .text(let tb) = block { return tb.text }
            return nil
        }.joined()

        VStack(alignment: .trailing, spacing: 8 * scale) {
            if let ctx = message.attachedContext {
                AttachedContextCardView(context: ctx, scale: scale)
            }
            UserBubbleView(text: text, scale: scale)
        }
    }

    @ViewBuilder
    private var assistantRow: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            ForEach(message.blocks) { block in
                blockView(block)
            }
        }
    }

    @ViewBuilder
    private func blockView(_ block: Block) -> some View {
        switch block {
        case .text(let tb):
            AssistantTextBlockView(
                block: tb,
                isStreaming: isStreamingText,
                scale: scale
            )
        case .status(let sb):
            StatusPillView(block: sb, scale: scale)
        case .stockCard(let scb):
            SingleStockCard(block: scb, scale: scale)
        }
    }
}

#Preview("User") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        MessageRowView(
            message: Message(id: UUID(), role: .user, blocks: [
                .text(TextBlock(blockId: "1", text: "How was Tesla's most recent earnings report?"))
            ]),
            isLastAssistantMessage: false,
            turnState: .idle,
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Assistant") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        MessageRowView(
            message: Message(id: UUID(), role: .assistant, blocks: [
                .text(TextBlock(blockId: "1", text: "Tesla reported strong Q4 earnings, beating analyst expectations on both revenue and EPS."))
            ]),
            isLastAssistantMessage: true,
            turnState: .idle,
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}
