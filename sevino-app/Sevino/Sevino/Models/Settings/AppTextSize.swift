import SwiftUI

enum AppTextSize: String, CaseIterable, Identifiable, Codable {
    case small, regular

    var id: String { rawValue }

    var multiplier: CGFloat {
        switch self {
        case .small: 1.0
        case .regular: 1.12
        }
    }

    var previewSize: CGFloat {
        switch self {
        case .small: 13
        case .regular: 17
        }
    }

    var label: String {
        switch self {
        case .small: L10n.Settings.textSizeSmall
        case .regular: L10n.Settings.textSizeRegular
        }
    }
}

private struct TextSizeMultiplierKey: EnvironmentKey {
    static let defaultValue: CGFloat = 1.0
}

extension EnvironmentValues {
    var textSizeMultiplier: CGFloat {
        get { self[TextSizeMultiplierKey.self] }
        set { self[TextSizeMultiplierKey.self] = newValue }
    }
}
