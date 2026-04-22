import XCTest

/**
 Acceptance tests for the unauthenticated entry flow.

 Covers the first screens a new user sees — Welcome, Log In, Sign Up — so a
 regression that hides a primary CTA or breaks navigation is caught at PR time.
 These tests assume no user is signed in on the simulator; launching the
 app drops the user on `WelcomeView`.
 */
final class WelcomeFlowUITests: XCTestCase {

    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments.append("-AppleLanguages")
        app.launchArguments.append("(en)")
        app.launch()
    }

    @MainActor
    func testWelcomeScreenShowsPrimaryCTAs() {
        let logIn = app.buttons["Log In"]
        let signUp = app.buttons["Sign Up"]

        XCTAssertTrue(logIn.waitForExistence(timeout: 5), "Log In button must be visible on launch")
        XCTAssertTrue(signUp.exists, "Sign Up button must be visible on launch")
        XCTAssertTrue(logIn.isHittable)
        XCTAssertTrue(signUp.isHittable)
    }

    @MainActor
    func testAppLogoIsExposedToAccessibility() {
        let logo = app.images["Sevino"]
        XCTAssertTrue(
            logo.waitForExistence(timeout: 5),
            "Sevino logo must have an accessibility label so VoiceOver announces the app name"
        )
    }

    @MainActor
    func testLogInCTANavigatesToSignInScreen() {
        app.buttons["Log In"].tap()

        // AuthView shows the "Welcome back" title for sign-in mode.
        let title = app.staticTexts["Welcome back"]
        XCTAssertTrue(title.waitForExistence(timeout: 3), "tapping Log In should present the sign-in screen")
    }

    @MainActor
    func testSignUpCTANavigatesToSignUpScreen() {
        app.buttons["Sign Up"].tap()

        // AuthView shows the "Let's get started" title for sign-up mode.
        let title = app.staticTexts["Let’s get started"]
        let alt = app.staticTexts["Let's get started"]
        XCTAssertTrue(
            title.waitForExistence(timeout: 3) || alt.waitForExistence(timeout: 1),
            "tapping Sign Up should present the sign-up screen"
        )
    }

    @MainActor
    func testBackFromAuthReturnsToWelcome() {
        app.buttons["Log In"].tap()
        _ = app.staticTexts["Welcome back"].waitForExistence(timeout: 3)

        app.buttons["Back"].tap()

        XCTAssertTrue(
            app.buttons["Log In"].waitForExistence(timeout: 3),
            "back button should return to welcome screen"
        )
    }

    @MainActor
    func testSignUpFormStartsWithSubmitDisabled() {
        app.buttons["Sign Up"].tap()
        _ = app.staticTexts["Let’s get started"].waitForExistence(timeout: 3)

        // The submit button shares the "Sign Up" label with the welcome-screen CTA,
        // so match the accessibility identifier explicitly to avoid resolving the wrong one.
        let submit = app.buttons["auth.submit"]
        XCTAssertTrue(submit.waitForExistence(timeout: 3), "submit button must be present on sign-up form")
        XCTAssertFalse(
            submit.isEnabled,
            "submit button must be disabled until email + password validation passes"
        )
    }
}
