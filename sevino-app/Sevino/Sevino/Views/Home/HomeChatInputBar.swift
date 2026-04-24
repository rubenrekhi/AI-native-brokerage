import SwiftUI

struct HomeChatInputBar: View {
    @Bindable var viewModel: TickerMentionViewModel
    let scale: CGFloat
    let isDimmed: Bool
    let onSend: ([MessageSegment]) -> Void
    let onQuickCommands: () -> Void
    @FocusState private var isFocused: Bool
    @State private var selection = AttributedTextSelection()
    @State private var showDiscoverPrompt = false

    private var hasText: Bool {
        !viewModel.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var attributedTextBinding: Binding<AttributedString> {
        Binding(
            get: { TickerMentionAttributedText.make(text: viewModel.text, tokens: viewModel.tokens, scale: scale) },
            set: { viewModel.updateText(String($0.characters)) }
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            TextEditor(text: attributedTextBinding, selection: $selection)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .scrollContentBackground(.hidden)
                .focused($isFocused)
                .frame(minHeight: 20 * scale, maxHeight: 100 * scale)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 16 * scale)
                .padding(.top, 14 * scale)
                .padding(.bottom, 8 * scale)
                .accessibilityLabel(L10n.Home.chatPlaceholder)
                .overlay(alignment: .topLeading) {
                    if viewModel.text.isEmpty {
                        Text(L10n.Home.chatPlaceholder)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.sevinoGreyAccent)
                            .padding(.leading, 16 * scale + 5)
                            .padding(.top, 14 * scale + 8)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    } else if showDiscoverPrompt && viewModel.text == "$" {
                        HStack(spacing: 0) {
                            Text(verbatim: "$")
                                .font(.system(size: 16 * scale))
                                .hidden()
                            Text(L10n.Home.quickCommandsDiscoverPlaceholder)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.sevinoGreyAccent)
                        }
                        .padding(.leading, 16 * scale + 5)
                        .padding(.top, 14 * scale + 8)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                    }
                }

            HStack(spacing: 0) {
                Button(L10n.Home.quickCommandsButtonAccessibility, systemImage: "plus", action: onQuickCommands)
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
        .onChange(of: viewModel.caretToEndTick) { _, _ in
            let attr = TickerMentionAttributedText.make(text: viewModel.text, tokens: viewModel.tokens, scale: scale)
            selection = AttributedTextSelection(insertionPoint: attr.endIndex)
        }
        .onChange(of: viewModel.focusRequestTick) { _, _ in
            isFocused = true
            showDiscoverPrompt = viewModel.text == "$"
            let attr = TickerMentionAttributedText.make(text: viewModel.text, tokens: viewModel.tokens, scale: scale)
            selection = AttributedTextSelection(insertionPoint: attr.endIndex)
        }
        .onChange(of: viewModel.text) { _, newValue in
            if newValue != "$" { showDiscoverPrompt = false }
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
        onSend: { _ in },
        onQuickCommands: {}
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
        onSend: { _ in },
        onQuickCommands: {}
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
        onSend: { _ in },
        onQuickCommands: {}
    )
    .padding()
}
