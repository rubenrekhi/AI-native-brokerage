import MarkdownUI
import SwiftUI

/// Renders a `TextBlock` as themed markdown.
///
/// During a streaming turn `block.text` grows as `text_delta` events arrive.
/// Binding `Markdown` directly to `block.text` made the surface "pop in" at
/// the backend chunk rate, so the view keeps a private `displayed` prefix that
/// the typewriter advances at character-rate cadence — see
/// `TypewriterStreamingBuffer`.
struct TextBlockView: View {
    @Environment(\.textSizeMultiplier) private var textSizeMultiplier
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let block: TextBlock

    /// `nil` until the view's first `.task` fires. The first run snaps to
    /// `block.text` so finalized messages re-entering the lazy list (or a
    /// hydrated history view) don't replay the typewriter from empty.
    @State private var displayed: String?

    var body: some View {
        Markdown(displayed ?? block.text)
            .markdownTheme(.sevino(scale: textSizeMultiplier))
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .task(id: TypewriterTrigger(text: block.text, reduceMotion: reduceMotion)) {
                await type(toward: block.text)
            }
    }

    private func type(toward target: String) async {
        guard let current = displayed else {
            displayed = target
            return
        }
        if reduceMotion || !target.hasPrefix(current) || target.count <= current.count {
            displayed = target
            return
        }
        var cursor = target.index(target.startIndex, offsetBy: current.count)
        let end = target.endIndex
        while cursor < end {
            if Task.isCancelled { return }
            let remaining = target.distance(from: cursor, to: end)
            let chunk = TypewriterStreamingBuffer.chunkSize(forRemaining: remaining)
            cursor = target.index(cursor, offsetBy: chunk, limitedBy: end) ?? end
            displayed = String(target[..<cursor])
            try? await Task.sleep(for: TypewriterAnimation.defaultSpeed)
        }
    }
}

/// Equatable trigger for `.task(id:)` so the typewriter restarts on both
/// streaming text changes and toggles of Reduce Motion mid-turn.
private struct TypewriterTrigger: Equatable {
    let text: String
    let reduceMotion: Bool
}

private extension Theme {
    static func sevino(scale: CGFloat) -> Theme {
        let baseSize = 16 * scale
        return Theme()
            .text {
                ForegroundColor(.sevinoSecondary)
                FontSize(baseSize)
            }
            .code {
                FontFamilyVariant(.monospaced)
                FontSize(.em(0.88))
                BackgroundColor(.sevinoAccent.opacity(0.5))
            }
            .strong {
                FontWeight(.semibold)
            }
            .emphasis {
                FontStyle(.italic)
            }
            .strikethrough { }
            .link {
                ForegroundColor(.sevinoHighlightText)
            }
            .heading1 { configuration in
                configuration.label
                    .markdownMargin(top: .em(0.8), bottom: .em(0.4))
                    .markdownTextStyle {
                        FontWeight(.bold)
                        FontSize(.em(1.5))
                    }
            }
            .heading2 { configuration in
                configuration.label
                    .markdownMargin(top: .em(0.7), bottom: .em(0.4))
                    .markdownTextStyle {
                        FontWeight(.semibold)
                        FontSize(.em(1.3))
                    }
            }
            .heading3 { configuration in
                configuration.label
                    .markdownMargin(top: .em(0.6), bottom: .em(0.3))
                    .markdownTextStyle {
                        FontWeight(.semibold)
                        FontSize(.em(1.15))
                    }
            }
            .paragraph { configuration in
                configuration.label
                    .markdownMargin(bottom: .em(0.6))
                    .lineSpacing(2 * scale)
            }
            .codeBlock { configuration in
                configuration.label
                    .markdownTextStyle {
                        FontFamilyVariant(.monospaced)
                        FontSize(.em(0.88))
                        ForegroundColor(.sevinoSecondary)
                    }
                    .padding(12 * scale)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.sevinoSettingsBg)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .markdownMargin(top: .em(0.5), bottom: .em(0.5))
            }
            .blockquote { configuration in
                configuration.label
                    .padding(.leading, 12 * scale)
                    .overlay(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(Color.sevinoGreyAccent)
                            .frame(width: 3)
                    }
                    .markdownMargin(top: .em(0.5), bottom: .em(0.5))
            }
            .listItem { configuration in
                configuration.label
                    .markdownMargin(top: .em(0.2))
            }
    }
}

#Preview("TextBlockView — formatting") {
    ScrollView {
        VStack(alignment: .leading, spacing: 24) {
            TextBlockView(
                block: TextBlock(
                    blockId: "preview_inline",
                    text: "Plain copy with **bold**, *italic*, `inline code`, and a [link](https://sevino.ai)."
                )
            )

            TextBlockView(
                block: TextBlock(
                    blockId: "preview_lists",
                    text: """
                    - First bullet
                    - Second bullet with **emphasis**
                    - Third bullet

                    1. Numbered one
                    2. Numbered two
                    3. Numbered three
                    """
                )
            )

            TextBlockView(
                block: TextBlock(
                    blockId: "preview_code",
                    text: """
                    Here's a code block:

                    ```swift
                    func greet(_ name: String) -> String {
                        "Hello, \\(name)!"
                    }
                    ```

                    > A blockquote for emphasis on a single point.
                    """
                )
            )

            TextBlockView(
                block: TextBlock(
                    blockId: "preview_headings",
                    text: """
                    # Heading one
                    ## Heading two
                    ### Heading three

                    Body copy underneath each heading.
                    """
                )
            )
        }
        .padding()
    }
    .background(Color.sevinoPrimary)
}
