import SwiftUI

struct MessageRowView: View {
    let message: Message
    let isLastAssistantMessage: Bool
    let turnState: ConversationStore.TurnState
    let scale: CGFloat

    @State private var sequencer = MessageTypewriterSequencer()

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
        // Status pills and stock cards don't get gated — only text blocks
        // are sequenced against each other.
        let ordinals = textBlockOrdinals(in: message.blocks)
        let lastTextOrdinal = ordinals.values.max() ?? -1
        VStack(alignment: .leading, spacing: 8 * scale) {
            if let source = message.cardContextSource {
                CardContextSourceChip(source: source, scale: scale)
            }
            ForEach(message.blocks) { block in
                blockView(block, ordinals: ordinals, lastTextOrdinal: lastTextOrdinal)
            }
        }
    }

    private func textBlockOrdinals(in blocks: [Block]) -> [String: Int] {
        var result: [String: Int] = [:]
        var ordinal = 0
        for case let .text(tb) in blocks {
            result[tb.blockId] = ordinal
            ordinal += 1
        }
        return result
    }

    @ViewBuilder
    private func blockView(
        _ block: Block,
        ordinals: [String: Int],
        lastTextOrdinal: Int
    ) -> some View {
        switch block {
        case .text(let tb):
            let ordinal = ordinals[tb.blockId] ?? 0
            AssistantTextBlockView(
                block: tb,
                isStreaming: isStreamingText,
                scale: scale,
                ordinal: ordinal,
                hasLaterTextBlock: ordinal < lastTextOrdinal,
                sequencer: sequencer
            )
        case .status(let sb):
            StatusPillView(block: sb, scale: scale)
        case .stockCard(let scb):
            SingleStockCard(block: scb, scale: scale)
        case .stockComparison(let scb):
            StockComparisonCard(block: scb, scale: scale)
        case .thinking(let tb):
            ThinkingBlockView(block: tb, scale: scale)
        case .cancelTransfer(let ctb):
            CancelTransferCard(block: ctb, scale: scale)
        case .cancelOrder(let cob):
            CancelOrderCard(block: cob, scale: scale)
        }
    }
}

private struct CardContextSourceChip: View {
    let source: CardContextSource
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 6 * scale) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 11 * scale, weight: .semibold))
            Text(source.displayText)
                .font(.system(size: 12 * scale, weight: .medium))
                .lineLimit(1)
                .minimumScaleFactor(0.86)
        }
        .foregroundStyle(Color.sevinoSecondary.opacity(0.72))
        .padding(.horizontal, 10 * scale)
        .padding(.vertical, 6 * scale)
        .background(Color.sevinoSecondary.opacity(0.08), in: .capsule)
        .accessibilityLabel(source.displayText)
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
