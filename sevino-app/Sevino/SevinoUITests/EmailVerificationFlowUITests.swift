import XCTest

/**
 Acceptance tests for the email verification screen (SEV-205).

 These tests bypass Supabase entirely by passing `--ui-test-mode=...` launch
 arguments — the app reads them in `SevinoApp` and swaps in
 `FakeAuthServiceForUITests` for the duration of the run. That lets us assert
 routing + view behavior in milliseconds instead of waiting on a real OTP
 round-trip and eyeballing Mailpit.

 ## Scope

 The tests here cover what XCUITest is uniquely good at: confirming the route
 actually drops the user on the screen with the right copy, and that the
 cooldown UI renders. The OTP submission state machine itself is exhaustively
 covered by `EmailVerificationViewModelTests` at the unit-test layer (~30
 tests including auto-submit, error mapping, retype-after-clear, race-resolution
 in `checkOnboardingStatus`, etc.) — re-asserting the same logic through the
 UI layer is duplicative and historically flaky in this codebase due to the
 `oneTimeCode` / `numberPad` keyboard's async input pipeline.

 ## Query strategy

 Elements are located by stable `accessibilityIdentifier`s declared on the
 view (e.g. `emailVerification.title`), not by their rendered English text.
 That keeps the suite green when copy editors retitle a string. When the
 *content* of the copy matters (e.g. confirming the email is interpolated
 into the title), a separate `XCTAssertEqual` on the resolved label is used.
 */
final class EmailVerificationFlowUITests: XCTestCase {

    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments.append(contentsOf: ["-AppleLanguages", "(en)"])
    }

    @MainActor
    func testEmailVerificationScreenRendersWithExpectedCopy() {
        app.launchArguments.append("--ui-test-mode=email-verification")
        app.launch()

        // Title — two stacked Text views combined into one accessibility element
        // via accessibilityElement(children: .combine). Located by identifier;
        // its label is the composed "title + email" string for VoiceOver.
        let title = app.staticTexts["emailVerification.title"]
        XCTAssertTrue(
            title.waitForExistence(timeout: 5),
            "the email verification screen should mount with the title element"
        )
        XCTAssertEqual(
            title.label,
            "We sent a code to uitest@sevino.ai",
            "title must interpolate the session email so users can verify they signed up with the right address"
        )

        let subtitle = app.staticTexts["emailVerification.subtitle"]
        XCTAssertTrue(subtitle.exists, "subtitle must be visible")

        let next = app.buttons["emailVerification.next"]
        XCTAssertTrue(next.exists, "Next button must be present")
        XCTAssertFalse(next.isEnabled, "Next must be disabled until 6 digits are entered")
    }

    @MainActor
    func testResendShowsCountdownOnEntry() {
        app.launchArguments.append("--ui-test-mode=email-verification")
        app.launch()

        XCTAssertTrue(
            app.staticTexts["emailVerification.title"].waitForExistence(timeout: 5)
        )

        // The resend section starts in cooldown (15s); the countdown text and
        // the resend button live behind separate identifiers so the test can
        // assert which is rendered without coupling to the localized format.
        let countdown = app.staticTexts["emailVerification.resendCountdown"]
        XCTAssertTrue(countdown.waitForExistence(timeout: 3), "cooldown countdown must show on entry")

        let resendButton = app.buttons["emailVerification.resend"]
        XCTAssertFalse(resendButton.exists, "Resend button must be hidden during the 15s cooldown")
    }
}
