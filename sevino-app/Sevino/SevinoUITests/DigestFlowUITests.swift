import XCTest

final class DigestFlowUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments.append(contentsOf: [
            "-AppleLanguages",
            "(en)",
            "--ui-test-mode=digest-flow",
        ])
    }

    @MainActor
    func testDigestLaunchesFullScreenAndDismissCollapsesToPeek() {
        app.launch()

        XCTAssertTrue(
            app.staticTexts["digest.title"].waitForExistence(timeout: 5),
            "today's digest should present full-screen on launch when an undismissed digest is available"
        )

        app.buttons["digest.close"].tap()

        XCTAssertTrue(
            app.buttons["digest.peek"].waitForExistence(timeout: 5),
            "dismissing the full-screen digest should leave the peek card visible"
        )
    }

    @MainActor
    func testSwipingPastLastCardRoutesToChat() {
        app.launch()

        XCTAssertTrue(app.staticTexts["digest.title"].waitForExistence(timeout: 5))

        app.swipeLeft()
        app.swipeLeft()

        XCTAssertTrue(
            app.staticTexts["digestUITest.chatRouted"].waitForExistence(timeout: 5),
            "swiping beyond the final digest card should dismiss the digest and route into chat"
        )
    }
}
