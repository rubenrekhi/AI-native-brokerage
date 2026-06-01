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
            // The default GitHub table fits the Grid to the bubble width, so cells
            // compress and wrap mid-phrase. Scrolling horizontally lets columns keep
            // their natural single-line width instead.
            .table { configuration in
                ScrollView(.horizontal, showsIndicators: false) {
                    configuration.label
                        .fixedSize(horizontal: false, vertical: true)
                        .markdownTableBorderStyle(.init(color: .sevinoGreyAccent.opacity(0.3)))
                        .markdownTableBackgroundStyle(
                            .alternatingRows(
                                Color.clear,
                                Color.sevinoGreyAccent.opacity(0.12),
                                header: Color.sevinoGreyAccent.opacity(0.2)
                            )
                        )
                }
                .markdownMargin(top: 0, bottom: 16 * scale)
            }
    }
}
