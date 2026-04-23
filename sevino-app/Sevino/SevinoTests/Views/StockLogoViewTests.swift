import XCTest
@testable import Sevino

final class StockLogoViewTests: XCTestCase {

    func testFallbackLetter_extractsFirstCharacterOfFilename() {
        let url = URL(string: "https://example.com/TSLA.png")
        XCTAssertEqual(StockLogoView.fallbackLetter(forLogoURL: url), "T")
    }

    func testFallbackLetter_returnsQuestionMarkForNilURL() {
        XCTAssertEqual(StockLogoView.fallbackLetter(forLogoURL: nil), "?")
    }

    func testFallbackLetter_returnsQuestionMarkForURLWithoutFilename() {
        let url = URL(string: "https://example.com/")
        XCTAssertEqual(StockLogoView.fallbackLetter(forLogoURL: url), "?")
    }
}
