import XCTest
@testable import Sevino

@MainActor
final class TickerTokenTextTests: XCTestCase {

    func testBuildTokens_textOnly_splitsOnWhitespace() {
        let tokens = TickerTokenText.buildTokens(from: [
            .text("How is my portfolio doing today?")
        ])
        XCTAssertEqual(tokens.map(\.token), [
            .word("How"), .word("is"), .word("my"),
            .word("portfolio"), .word("doing"), .word("today?")
        ])
    }

    func testBuildTokens_leadingTicker_preservesOrder() {
        let tokens = TickerTokenText.buildTokens(from: [
            .ticker("NVDA"),
            .text(" is up 3% this week")
        ])
        XCTAssertEqual(tokens.map(\.token), [
            .ticker("NVDA"),
            .word("is"), .word("up"), .word("3%"), .word("this"), .word("week")
        ])
    }

    func testBuildTokens_trailingTicker_preservesOrder() {
        let tokens = TickerTokenText.buildTokens(from: [
            .text("Show me "),
            .ticker("AAPL")
        ])
        XCTAssertEqual(tokens.map(\.token), [
            .word("Show"), .word("me"), .ticker("AAPL")
        ])
    }

    func testBuildTokens_consecutiveTickers_eachBecomesOwnToken() {
        let tokens = TickerTokenText.buildTokens(from: [
            .ticker("AAPL"),
            .ticker("MSFT"),
            .ticker("GOOGL")
        ])
        XCTAssertEqual(tokens.map(\.token), [
            .ticker("AAPL"), .ticker("MSFT"), .ticker("GOOGL")
        ])
    }

    func testBuildTokens_emptyTextSegment_producesNoWordTokens() {
        let tokens = TickerTokenText.buildTokens(from: [
            .text(""),
            .ticker("TSLA"),
            .text("")
        ])
        XCTAssertEqual(tokens.map(\.token), [.ticker("TSLA")])
    }

    func testBuildTokens_assignsStableUniqueIds() {
        let tokens = TickerTokenText.buildTokens(from: [
            .text("the the"),
            .ticker("AAPL"),
            .ticker("AAPL")
        ])
        let ids = tokens.map(\.id)
        XCTAssertEqual(ids, [0, 1, 2, 3])
        XCTAssertEqual(Set(ids).count, ids.count, "ids must be unique even when tokens repeat")
    }

    func testBuildTokens_empty_returnsEmpty() {
        XCTAssertTrue(TickerTokenText.buildTokens(from: []).isEmpty)
    }
}
