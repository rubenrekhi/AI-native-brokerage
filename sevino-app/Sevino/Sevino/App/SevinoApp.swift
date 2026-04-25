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
                ContentView()
                    .environment(\.textSizeMultiplier, textMultiplier)
                    .task { applyTheme() }
                    .onChange(of: appTheme) { applyTheme() }
            }
        }
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
