#if DEBUG
import Foundation
import Observation
import SwiftUI

/// Centralized launch-argument parsing for XCUITest. Lets the test bundle drive
/// the running app into a known state without spinning up a real backend.
/// Production (Release) builds compile this file out, so the fakes can never
/// ship in a shipping binary.
enum UITestLaunchArgument {
    /// Reads `--ui-test-mode=<value>` from `CommandLine.arguments`. Returns nil
    /// if no mode flag is present (the normal app launch path).
    static var mode: String? {
        parsedMode?.rawValue
    }

    static var parsedMode: Mode? {
        let prefix = "--ui-test-mode="
        for arg in CommandLine.arguments {
            if arg.hasPrefix(prefix) {
                return Mode(rawValue: String(arg.dropFirst(prefix.count)))
            }
        }
        return nil
    }

    /// Mode values the app recognizes. Tests pass these via
    /// `app.launchArguments.append("--ui-test-mode=<rawValue>")`.
    enum Mode: String {
        /// Drop straight onto the email verification screen with a fake auth
        /// service in the unverified state. Lets tests assert routing + view
        /// behavior without spinning up Supabase.
        case emailVerification = "email-verification"
        /// Force the unauthenticated path so the welcome screen is on top
        /// regardless of any persisted Supabase session in the simulator
        /// keychain. Used by WelcomeFlowUITests.
        case unauthenticated = "unauthenticated"
        /// Mounts a deterministic digest host for full-screen digest
        /// acceptance coverage without involving auth or backend state.
        case digestFlow = "digest-flow"
    }
}

/// `AuthServiceProtocol` stub used only by XCUITest. Configured at process
/// launch from `UITestLaunchArgument.mode`. Mutating state (verify, resend)
/// happens in-memory and synchronously, so the test can drive the UI without
/// network round-trips or simulator clock dependencies.
@Observable
final class FakeAuthServiceForUITests: AuthServiceProtocol {
    var isAuthenticated: Bool
    var isEmailVerified: Bool
    var emailResendAvailableAt: Date?
    var canResendEmailConfirmation: Bool { true }
    var accessToken: String? { "fake-ui-test-token" }
    var currentEmail: String?

    init(
        isAuthenticated: Bool = true,
        isEmailVerified: Bool = false,
        currentEmail: String? = "uitest@sevino.ai"
    ) {
        self.isAuthenticated = isAuthenticated
        self.isEmailVerified = isEmailVerified
        self.currentEmail = currentEmail
    }

    func signUp(email: String, password: String) async throws {}
    func signIn(email: String, password: String) async throws { isAuthenticated = true }
    func signOut() async throws {
        isAuthenticated = false
        isEmailVerified = false
    }
    func updatePassword(currentPassword: String, newPassword: String) async throws {}
    func resendEmailConfirmation(email: String) async throws {}
    func verifyEmailConfirmation(email: String, code: String) async throws {
        isEmailVerified = true
    }
}

extension FakeAuthServiceForUITests {
    /// Builds a fake configured according to the launch-arg mode. Returns nil
    /// when no mode flag is set, signaling the app should fall back to the
    /// normal `AuthService.shared` wiring.
    static func makeFromLaunchArguments() -> FakeAuthServiceForUITests? {
        guard let mode = UITestLaunchArgument.parsedMode else { return nil }

        switch mode {
        case .emailVerification:
            return FakeAuthServiceForUITests()
        case .unauthenticated:
            return FakeAuthServiceForUITests(
                isAuthenticated: false, currentEmail: nil
            )
        case .digestFlow:
            return nil
        }
    }
}

struct DigestUITestHostView: View {
    @State private var viewModel = DigestViewModel(client: PlaceholderDigestAPIClient())
    @State private var routedToChat = false

    private var digestCoverPresented: Binding<Bool> {
        Binding(
            get: { viewModel.presentationState == .full },
            set: { isPresented in
                if !isPresented && viewModel.presentationState == .full {
                    Task { await viewModel.dismissToPeek() }
                }
            }
        )
    }

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()

            VStack(spacing: 24) {
                if routedToChat {
                    Text(verbatim: "Digest routed to chat")
                        .foregroundStyle(Color.sevinoSecondary)
                        .accessibilityIdentifier("digestUITest.chatRouted")
                }

                if viewModel.presentationState == .peek {
                    PeekCardView(
                        scale: 1,
                        cardCount: viewModel.cards.count,
                        onTap: viewModel.reopenDigest
                    )
                    .padding(.horizontal, 16)
                }
            }
        }
        .task { await viewModel.refreshForForeground() }
        .fullScreenCover(isPresented: digestCoverPresented) {
            DigestStackView(
                scale: 1,
                viewModel: viewModel,
                onRouteToChat: { routedToChat = true }
            )
        }
    }
}
#endif
