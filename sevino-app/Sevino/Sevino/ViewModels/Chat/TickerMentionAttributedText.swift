import SwiftUI

enum TickerMentionAttributedText {
    static func make(text: String, tokens: [TickerToken], scale: CGFloat) -> AttributedString {
        var attr = AttributedString(text)
        let chars = attr.characters
        for token in tokens {
            guard
                let lower = chars.index(chars.startIndex, offsetBy: token.range.lowerBound, limitedBy: chars.endIndex),
                let upper = chars.index(chars.startIndex, offsetBy: token.range.upperBound, limitedBy: chars.endIndex)
            else { continue }
            attr[lower..<upper].font = .system(size: 16 * scale, weight: .semibold)
            attr[lower..<upper].foregroundColor = Color.sevinoHighlightText
            attr[lower..<upper].backgroundColor = Color.sevinoHighlightBg
        }
        return attr
    }
}
