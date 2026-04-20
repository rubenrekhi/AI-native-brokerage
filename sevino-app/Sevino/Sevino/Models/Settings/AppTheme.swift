import Foundation

enum AppTheme: String, CaseIterable, Identifiable {
    case light, dark, system

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .light: "sun.max"
        case .dark: "moon"
        case .system: "gearshape"
        }
    }

    var label: String {
        switch self {
        case .light: L10n.Settings.themeLight
        case .dark: L10n.Settings.themeDark
        case .system: L10n.Settings.themeSystem
        }
    }
}
