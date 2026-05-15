import SwiftUI
import MarkdownUI

extension Theme {
    static func sevino(scale: CGFloat) -> Theme {
        .gitHub
            .text {
                ForegroundColor(Color.sevinoSecondary)
                FontSize(16 * scale)
            }
            .heading1 { configuration in
                configuration.label
                    .markdownTextStyle {
                        FontSize(24 * scale)
                        FontWeight(.bold)
                        ForegroundColor(Color.sevinoSecondary)
                    }
            }
            .heading2 { configuration in
                configuration.label
                    .markdownTextStyle {
                        FontSize(20 * scale)
                        FontWeight(.bold)
                        ForegroundColor(Color.sevinoSecondary)
                    }
            }
            .heading3 { configuration in
                configuration.label
                    .markdownTextStyle {
                        FontSize(18 * scale)
                        FontWeight(.semibold)
                        ForegroundColor(Color.sevinoSecondary)
                    }
            }
            .code {
                FontSize(14 * scale)
                ForegroundColor(Color.sevinoHighlightText)
            }
    }
}
