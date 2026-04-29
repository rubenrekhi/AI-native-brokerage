import SwiftUI

/// Read-only popup that displays the user's current email. Email changes are
/// gated behind support because Supabase requires re-verification, so the
/// popup omits the Save action entirely.
struct EditEmailSheet: View {
    let email: String

    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        SettingsEditPopup(
            title: L10n.Settings.editEmailTitle,
            scale: scale,
            saveAction: nil
        ) {
            SettingsEditPopupSection(label: L10n.Settings.emailLabel, scale: scale) {
                SettingsEditPopupReadOnlyValue(value: email, scale: scale)
            }

            SettingsEditPopupHelperText(text: L10n.Settings.editEmailExplanation, scale: scale)
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
    }
}

#if DEBUG
#Preview("Email") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditEmailSheet(email: "ready.riley@sevino.ai")
        }
        .preferredColorScheme(.dark)
}

#Preview("Missing") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditEmailSheet(email: L10n.Settings.missingValuePlaceholder)
        }
        .preferredColorScheme(.dark)
}
#endif
