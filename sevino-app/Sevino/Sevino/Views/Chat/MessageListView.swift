import SwiftUI

struct MessageListView: View {
    let messages: [Message]
    var scale: CGFloat = 1

    // Sentinel id is stable across renders so `scrollTo` lands at the
    // true tail even when the last message's last block keeps mutating —
    // `text_delta` events flip array equality without changing `message.id`.
    private static let bottomAnchorID = "MessageListView.bottom"

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20 * scale) {
                    ForEach(messages) { message in
                        MessageRow(message: message, scale: scale)
                            .id(message.id)
                    }
                    Color.clear
                        .frame(height: 1)
                        .id(Self.bottomAnchorID)
                }
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 12 * scale)
            }
            .scrollDismissesKeyboard(.interactively)
            // Animated jump for new turns; unanimated stick-to-bottom for
            // intra-message updates so per-chunk `text_delta` events don't
            // pile up overlapping easeOut animations on the scroll position.
            .onChange(of: messages.count) { _, _ in
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
                }
            }
            .onChange(of: messages.last?.blocks) { _, _ in
                proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
            }
            .onAppear {
                proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
            }
        }
    }
}

private struct MessageRow: View {
    let message: Message
    let scale: CGFloat

    var body: some View {
        switch message.role {
        case .user:
            UserMessageRow(message: message, scale: scale)
        case .assistant:
            AssistantMessageRow(message: message, scale: scale)
        }
    }
}

private struct UserMessageRow: View {
    let message: Message
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .trailing, spacing: 8 * scale) {
            ForEach(message.blocks) { block in
                BlockView(block: block, scale: scale)
                    .padding(.horizontal, 14 * scale)
                    .padding(.vertical, 10 * scale)
                    .background(
                        RoundedRectangle(cornerRadius: 18 * scale)
                            .fill(Color.sevinoGreyAccent.opacity(0.25))
                    )
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }
}

private struct AssistantMessageRow: View {
    let message: Message
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            ForEach(message.blocks) { block in
                BlockView(block: block, scale: scale)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct BlockView: View {
    let block: Block
    let scale: CGFloat

    var body: some View {
        switch block {
        case .text(let textBlock):
            TextBlockView(block: textBlock)
        case .status(let statusBlock):
            StatusPillView(block: statusBlock)
        case .stockCard(let stockCardBlock):
            // TODO(SEV-509): replace with SingleStockCard(block:).
            StockCardPlaceholder(block: stockCardBlock, scale: scale)
        }
    }
}

private struct StockCardPlaceholder: View {
    let block: StockCardBlock
    let scale: CGFloat

    var body: some View {
        Text(L10n.Chat.stockCardPlaceholder(block.symbol))
            .font(.system(size: 13 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoGreyContrast)
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 10 * scale)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 12 * scale)
                    .fill(Color.sevinoGreyAccent.opacity(0.15))
            )
    }
}

#Preview("Mixed blocks") {
    let messages: [Message] = [
        Message(
            id: UUID(),
            role: .user,
            blocks: [
                .text(TextBlock(blockId: "u1", text: "What's AMD doing today?"))
            ]
        ),
        Message(
            id: UUID(),
            role: .assistant,
            blocks: [
                .status(StatusBlock(blockId: "s1", label: "Fetched AMD price", state: .complete)),
                .text(TextBlock(
                    blockId: "t1",
                    text: "AMD is trading at **$184.92**, up *0.53%* on the day. The chart below shows the past month."
                )),
                .stockCard(StockCardBlock(
                    blockId: "sc1",
                    symbol: "AMD",
                    companyName: "Advanced Micro Devices Inc.",
                    logoUrl: nil,
                    price: 184.92,
                    changeAbs: 2.12,
                    changePct: 0.0053,
                    colorState: .positive,
                    bars: [],
                    range: "1M",
                    rangeOptions: ["1D", "1W", "1M"]
                ))
            ]
        ),
        Message(
            id: UUID(),
            role: .user,
            blocks: [
                .text(TextBlock(blockId: "u2", text: "Thanks!"))
            ]
        )
    ]

    return MessageListView(messages: messages)
        .background(Color.sevinoPrimary)
}

#Preview("Streaming in-flight") {
    let messages: [Message] = [
        Message(
            id: UUID(),
            role: .user,
            blocks: [
                .text(TextBlock(blockId: "u1", text: "What's AMD doing?"))
            ]
        ),
        Message(
            id: UUID(),
            role: .assistant,
            blocks: [
                .status(StatusBlock(blockId: "s1", label: "Fetching AMD price", state: .active))
            ]
        )
    ]

    return MessageListView(messages: messages)
        .background(Color.sevinoPrimary)
}

#Preview("Empty") {
    MessageListView(messages: [])
        .background(Color.sevinoPrimary)
}
