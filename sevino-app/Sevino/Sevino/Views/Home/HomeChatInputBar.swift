import SwiftUI

struct HomeChatInputBar: View {
    @Bindable var viewModel: TickerMentionViewModel
    let scale: CGFloat
    let isDimmed: Bool
    let onSend: ([MessageSegment]) -> Void
    @FocusState private var isFocused: Bool

    private var hasText: Bool {
        !viewModel.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var textBinding: Binding<String> {
        Binding(
            get: { viewModel.text },
            set: { viewModel.updateText($0) }
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            TextField(L10n.Home.chatPlaceholder, text: textBinding, axis: .vertical)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .lineLimit(1...5)
                .focused($isFocused)
                .padding(.horizontal, 16 * scale)
                .padding(.top, 14 * scale)
                .padding(.bottom, 8 * scale)

            HStack(spacing: 0) {
                Button(L10n.Home.attachAccessibility, systemImage: "plus", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Spacer()

                Button(L10n.Home.micAccessibility, systemImage: "mic", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Button(L10n.Home.sendAccessibility, systemImage: "arrow.up", action: sendMessage)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(hasText ? Color.sevinoPrimary : Color.sevinoGreyAccent)
                    .frame(width: 30 * scale, height: 30 * scale)
                    .background(hasText ? Color.homeSendActiveBg : .clear, in: .circle)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .disabled(!hasText)
            }
            .padding(.horizontal, 4 * scale)
            .padding(.bottom, 4 * scale)
        }
        .modifier(SevinoGlass.card)
        .onChange(of: isDimmed) { _, newValue in
            if newValue {
                isFocused = false
                viewModel.dismiss()
            }
        }
    }

    private func sendMessage() {
        guard hasText else { return }
        onSend(viewModel.makeSegments())
    }
}

#Preview("Empty") {
    HomeChatInputBar(
        viewModel: TickerMentionViewModel(),
        scale: 1,
        isDimmed: false,
        onSend: { _ in }
    )
    .padding()
}

#Preview("With text") {
    let viewModel = TickerMentionViewModel()
    viewModel.updateText("Hello")
    return HomeChatInputBar(
        viewModel: viewModel,
        scale: 1,
        isDimmed: false,
        onSend: { _ in }
    )
    .padding()
}

#Preview("Dimmed") {
    let viewModel = TickerMentionViewModel()
    viewModel.updateText("Hello")
    return HomeChatInputBar(
        viewModel: viewModel,
        scale: 1,
        isDimmed: true,
        onSend: { _ in }
    )
    .padding()
}
