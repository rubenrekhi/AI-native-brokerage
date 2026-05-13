import SwiftUI

struct MessageListView: View {
    let messages: [Message]
    let turnState: ConversationStore.TurnState
    let scale: CGFloat
    var onRetry: (() -> Void)?

    private enum Anchor {
        case bottom
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    let lastAssistantIdx = messages.lastIndex(where: { $0.role == .assistant })
                    ForEach(Array(messages.enumerated()), id: \.element.id) { index, message in
                        MessageRowView(
                            message: message,
                            isLastAssistantMessage: index == lastAssistantIdx,
                            turnState: turnState,
                            scale: scale
                        )
                        .padding(.top, index == 0 ? 0 : spacingBefore(index: index))
                    }

                    if case .error(let code, let message) = turnState, let onRetry {
                        ChatErrorBannerView(
                            code: code,
                            message: message,
                            scale: scale,
                            onRetry: onRetry
                        )
                        .padding(.top, 12 * scale)
                    }

                    Color.clear
                        .frame(height: 1)
                        .id(Anchor.bottom)
                }
                .padding(.vertical, 16 * scale)
            }
            .scrollIndicators(.hidden)
            .mask {
                VStack(spacing: 0) {
                    LinearGradient(
                        colors: [.clear, .black],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                    .frame(height: 40 * scale)
                    Color.black
                }
                .ignoresSafeArea()
            }
            .onChange(of: messages.count) { _, _ in
                scrollToBottom(proxy, animated: true)
            }
            .onChange(of: messages.last?.blocks) { _, _ in
                scrollToBottom(proxy, animated: false)
            }
            .onChange(of: turnState) { oldState, newState in
                if oldState == .streaming && newState == .idle {
                    scrollToBottom(proxy, animated: true)
                }
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool) {
        if animated {
            withAnimation(.easeOut(duration: 0.2)) {
                proxy.scrollTo(Anchor.bottom, anchor: .bottom)
            }
        } else {
            proxy.scrollTo(Anchor.bottom, anchor: .bottom)
        }
    }

    private func spacingBefore(index: Int) -> CGFloat {
        guard index > 0 else { return 0 }
        let prev = messages[index - 1].role
        let curr = messages[index].role
        return prev == curr ? 12 * scale : 20 * scale
    }
}

#Preview {
    MessageListView(
        messages: [
            Message(id: UUID(), role: .user, blocks: [
                .text(TextBlock(blockId: "1", text: "How is Tesla doing?"))
            ]),
            Message(id: UUID(), role: .assistant, blocks: [
                .thinking(ThinkingBlock(
                    blockId: "th1",
                    text: "User asked about Tesla. Let me pull the latest figures.",
                    redacted: false,
                    state: .complete
                )),
                .text(TextBlock(blockId: "2", text: "Tesla is currently trading at $443.30, up 0.08% over the past 3 months."))
            ])
        ],
        turnState: .idle,
        scale: 1
    )
    .background(Color.sevinoPrimary)
    .preferredColorScheme(.dark)
}
