import MarkdownUI
import SwiftUI

/// Renders a `TextBlock` as themed markdown. Theme matches the Sevino chat aesthetic.
struct TextBlockView: View {
    @Environment(\.textSizeMultiplier) private var textSizeMultiplier
    let block: TextBlock

    var body: some View {
        Markdown(block.text)
            .markdownTheme(.sevino(scale: textSizeMultiplier))
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
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
