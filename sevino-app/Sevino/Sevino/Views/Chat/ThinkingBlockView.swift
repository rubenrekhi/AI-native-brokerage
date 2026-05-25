import SwiftUI

/**
 Expandable chip surfacing the model's extended-thinking output (SEV-571).

 During a streaming turn the chip auto-expands so the user can watch the
 chain-of-thought unfold, then auto-collapses when the model finishes
 thinking — unless the user has manually toggled it, in which case we
 honour the user's intent for the remainder of the turn. Tap anywhere
 on the header to toggle.

 `redacted == true` covers Anthropic's `redacted_thinking` variant.
 Those blocks arrive with `state == .complete` and no body text; the
 expanded view shows a stub line instead.

 The view is intentionally quieter than `AssistantTextBlockView`:
 smaller font, muted colour, italic copy — so it reads as "internal
 reasoning, not the answer." See the SEV-571 acceptance criteria for
 the full UX contract.

 Sized via `scale` to match the convention shared with other chat
 block views (e.g. `StatusPillView`, `SingleStockCard`): each block
 view applies its own outer horizontal padding so the message column
 can grow with the user's text-size setting.
 */
struct ThinkingBlockView: View {
    private static let cornerRadius: CGFloat = 10

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let block: ThinkingBlock
    let scale: CGFloat

    @State private var isExpanded: Bool
    /// Set on the first user tap; suppresses auto-collapse for the rest of the turn.
    @State private var userToggled = false

    init(block: ThinkingBlock, scale: CGFloat) {
        self.block = block
        self.scale = scale
        _isExpanded = State(initialValue: block.state == .streaming)
    }

    /// Preview-only override that pins both `isExpanded` and the
    /// `userToggled` flag so static snapshots can show states the
    /// production initialiser can't synthesise (e.g. streaming-while-
    /// collapsed, which only occurs after a user tap).
    fileprivate init(
        block: ThinkingBlock,
        scale: CGFloat,
        initialExpanded: Bool,
        userToggled: Bool = true
    ) {
        self.block = block
        self.scale = scale
        _isExpanded = State(initialValue: initialExpanded)
        _userToggled = State(initialValue: userToggled)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            header
            if isExpanded {
                expandedBody
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(12 * scale)
        .background(
            RoundedRectangle(cornerRadius: Self.cornerRadius * scale)
                .fill(Color.sevinoGreyAccent.opacity(0.18))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Self.cornerRadius * scale)
                .strokeBorder(Color.sevinoGreyAccent.opacity(0.3), lineWidth: 0.5)
        )
        .padding(.horizontal, 16 * scale)
        .animation(animation, value: isExpanded)
        .onChange(of: block.state) { _, newState in
            guard !userToggled else { return }
            if newState == .complete {
                isExpanded = false
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityValue(accessibilityValue)
        .accessibilityHint(L10n.Chat.thinkingAccessibilityHint)
        .accessibilityAddTraits(.isButton)
        // Expose the toggle to VoiceOver. The inner `Button` is hidden
        // from accessibility (so the combined element advertises a
        // single coherent label rather than the button label + body
        // text), which means the Button's action is also hidden — so
        // we re-attach it here.
        .accessibilityAction {
            userToggled = true
            isExpanded.toggle()
        }
    }

    private var header: some View {
        Button {
            userToggled = true
            isExpanded.toggle()
        } label: {
            HStack(spacing: 8 * scale) {
                Image(systemName: "chevron.right")
                    .font(.system(size: 11 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .rotationEffect(.degrees(isExpanded ? 90 : 0))
                    .animation(animation, value: isExpanded)

                Text(headerLabel)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .lineLimit(1)

                Spacer(minLength: 0)
            }
            .frame(minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var expandedBody: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            if block.redacted {
                Text(L10n.Chat.thinkingRedactedBody)
                    .font(.system(size: 13 * scale).italic())
                    .foregroundStyle(Color.sevinoGreyContrast)
            } else if !block.text.isEmpty {
                Text(block.text)
                    .font(.system(size: 13 * scale).italic())
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            Text(L10n.Chat.thinkingDisclaimer)
                .font(.system(size: 11 * scale))
                .foregroundStyle(Color.sevinoGreyContrast.opacity(0.7))
        }
    }

    private var headerLabel: String {
        if block.state == .streaming && !block.redacted {
            return L10n.Chat.thinkingStreamingHeader
        }
        return L10n.Chat.thinkingHeader
    }

    private var animation: Animation? {
        reduceMotion ? nil : .easeInOut(duration: 0.22)
    }

    private var accessibilityLabel: String {
        isExpanded
            ? L10n.Chat.thinkingAccessibilityExpanded
            : L10n.Chat.thinkingAccessibilityCollapsed
    }

    private var accessibilityValue: String {
        guard isExpanded else { return "" }
        if block.redacted { return L10n.Chat.thinkingRedactedBody }
        // While streaming, expose a static stub so VoiceOver doesn't
        // re-announce the growing text on every `text_delta`. The
        // final reasoning becomes the accessibility value at
        // `.complete`.
        if block.state == .streaming { return L10n.Chat.thinkingStreamingHeader }
        return block.text
    }
}

#Preview("Streaming, expanded") {
    // Default auto-expand path: the chip pops open as the model starts
    // thinking and the body grows with each `text_delta`.
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ThinkingBlockView(
            block: ThinkingBlock(
                blockId: "1",
                text: "The user is asking about AMD's recent performance. Let me consider the data carefully — AMD has been trading in a range",
                redacted: false,
                state: .streaming
            ),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Streaming, collapsed (user toggled)") {
    // The user tapped the chip closed while it's still streaming.
    // Production code only reaches this state via a manual tap; the
    // fileprivate init lets the preview pin both `isExpanded` and
    // `userToggled` so the snapshot reproduces it faithfully.
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ThinkingBlockView(
            block: ThinkingBlock(
                blockId: "2",
                text: "Some thoughts here…",
                redacted: false,
                state: .streaming
            ),
            scale: 1,
            initialExpanded: false
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Complete, collapsed") {
    // Auto-collapse path: streaming finished, user hasn't pinned the
    // chip open, so it reads as a quiet "Thought" pill.
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ThinkingBlockView(
            block: ThinkingBlock(
                blockId: "3",
                text: "Final reasoning here.",
                redacted: false,
                state: .complete
            ),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Complete, expanded (user toggled open)") {
    // The user re-opens the chip after the model finished thinking —
    // `userToggled` is set so the auto-collapse `onChange` doesn't
    // fight the user's intent on subsequent state transitions.
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ThinkingBlockView(
            block: ThinkingBlock(
                blockId: "4",
                text: "AMD's chart shows a mild uptrend over the past month with three notable consolidation points. Considering the overall semiconductor cycle, this looks consistent with peers.",
                redacted: false,
                state: .complete
            ),
            scale: 1,
            initialExpanded: true
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Redacted") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ThinkingBlockView(
            block: ThinkingBlock(
                blockId: "5",
                text: "",
                redacted: true,
                state: .complete
            ),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}
