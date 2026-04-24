import XCTest
import SwiftUI
@testable import Sevino

@MainActor
final class TickerMentionAttributedTextTests: XCTestCase {

    func testEmptyTextProducesEmptyAttributedString() {
        let attr = TickerMentionAttributedText.make(text: "", tokens: [], scale: 1)
        XCTAssertTrue(attr.characters.isEmpty)
    }

    func testPlainTextWithoutTokensHasNoHighlightAttributes() {
        let attr = TickerMentionAttributedText.make(text: "Hello world", tokens: [], scale: 1)
        XCTAssertEqual(String(attr.characters), "Hello world")
        XCTAssertNil(attr.foregroundColor)
        XCTAssertNil(attr.backgroundColor)
        XCTAssertNil(attr.font)
    }

    func testTokenRangeGetsHighlightColorsAndSemiboldFont() {
        let tokens = [TickerToken(symbol: "TSLA", range: 4..<9)]
        let attr = TickerMentionAttributedText.make(text: "Buy $TSLA now", tokens: tokens, scale: 1)

        let chars = attr.characters
        let lower = chars.index(chars.startIndex, offsetBy: 4)
        let upper = chars.index(chars.startIndex, offsetBy: 9)

        XCTAssertEqual(attr[lower..<upper].foregroundColor, Color.sevinoHighlightText)
        XCTAssertEqual(attr[lower..<upper].backgroundColor, Color.sevinoHighlightBg)
        XCTAssertEqual(attr[lower..<upper].font, .system(size: 16, weight: .semibold))
    }

    func testSurroundingCharactersAreNotHighlighted() {
        let tokens = [TickerToken(symbol: "TSLA", range: 4..<9)]
        let attr = TickerMentionAttributedText.make(text: "Buy $TSLA now", tokens: tokens, scale: 1)

        let chars = attr.characters
        let leadingEnd = chars.index(chars.startIndex, offsetBy: 4)
        XCTAssertNil(attr[chars.startIndex..<leadingEnd].foregroundColor)

        let trailingStart = chars.index(chars.startIndex, offsetBy: 9)
        XCTAssertNil(attr[trailingStart..<chars.endIndex].foregroundColor)
    }

    func testMultipleTokensEachGetHighlighted() {
        let tokens = [
            TickerToken(symbol: "TSLA", range: 0..<5),
            TickerToken(symbol: "AMD", range: 10..<14),
        ]
        let attr = TickerMentionAttributedText.make(text: "$TSLA and $AMD", tokens: tokens, scale: 1)

        let chars = attr.characters
        for range in [0..<5, 10..<14] {
            let lower = chars.index(chars.startIndex, offsetBy: range.lowerBound)
            let upper = chars.index(chars.startIndex, offsetBy: range.upperBound)
            XCTAssertEqual(attr[lower..<upper].foregroundColor, Color.sevinoHighlightText)
        }
    }

    func testOutOfBoundsTokenIsSkippedWithoutCrash() {
        let tokens = [TickerToken(symbol: "TSLA", range: 100..<200)]
        let attr = TickerMentionAttributedText.make(text: "short", tokens: tokens, scale: 1)
        XCTAssertEqual(String(attr.characters), "short")
        XCTAssertNil(attr.foregroundColor)
    }

    func testScaleMultiplierIsAppliedToFontSize() {
        let tokens = [TickerToken(symbol: "T", range: 0..<2)]
        let attr = TickerMentionAttributedText.make(text: "$T", tokens: tokens, scale: 1.5)

        let chars = attr.characters
        let lower = chars.startIndex
        let upper = chars.index(chars.startIndex, offsetBy: 2)

        XCTAssertEqual(attr[lower..<upper].font, .system(size: 24, weight: .semibold))
    }
}
