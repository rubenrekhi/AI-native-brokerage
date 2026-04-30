import SwiftUI

@main
struct SevinoApp: App {
    private static let isTesting = ProcessInfo.processInfo.environment.keys.contains("XCTestBundlePath")

    @AppStorage("appTheme") private var appTheme = AppTheme.system.rawValue
    @AppStorage("appTextSize") private var appTextSize = AppTextSize.small.rawValue

    private var textMultiplier: CGFloat {
        (AppTextSize(rawValue: appTextSize) ?? .small).multiplier
    }

    var body: some Scene {
        WindowGroup {
            if Self.isTesting {
                // Avoid initializing AuthService.shared (and the Supabase
                // connection) when the app is launched as a test host.
                Text(verbatim: "Running tests…")
            } else {
                contentView
                    .environment(\.textSizeMultiplier, textMultiplier)
                    .task { applyTheme() }
                    .onChange(of: appTheme) { applyTheme() }
            }
        }
    }

    /// Picks the right `ContentView` wiring. In normal launches this returns the
    /// default `ContentView()`; under XCUITest a fake `AuthService` is injected
    /// when `--ui-test-mode=...` is set so tests can drive the auth state without
    /// hitting Supabase. The `#if DEBUG` keeps the fake out of Release builds.
    @ViewBuilder
    private var contentView: some View {
        #if DEBUG
        if let fake = FakeAuthServiceForUITests.makeFromLaunchArguments() {
            ContentView(
                authVM: AuthViewModel(authService: fake),
                viewModel: ContentViewModel(authService: fake)
            )
        } else {
            ContentView()
        }
        #else
        ContentView()
        #endif
    }

    private func applyTheme() {
        let style: UIUserInterfaceStyle = switch AppTheme(rawValue: appTheme) {
        case .light: .light
        case .dark: .dark
        case .system, .none: .unspecified
        }
        for scene in UIApplication.shared.connectedScenes {
            guard let windowScene = scene as? UIWindowScene else { continue }
            for window in windowScene.windows {
                window.overrideUserInterfaceStyle = style
            }
        }
    }
}
