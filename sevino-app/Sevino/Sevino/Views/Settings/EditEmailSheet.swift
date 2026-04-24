import SwiftUI

/// Read-only sheet that displays the user's current email. Email changes are
/// gated behind support because Supabase requires re-verification.
struct EditEmailSheet: View {
    let email: String

    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                emailCard
                    .padding(.bottom, 16 * scale)

                Text(L10n.Settings.editEmailExplanation)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Spacer()
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
    }

    private var header: some View {
        ZStack {
            Text(L10n.Settings.editEmailTitle)
                .font(.system(size: 20 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            HStack {
                Spacer()

                Button(L10n.Settings.editSheetDone) { dismiss() }
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .contentShape(Rectangle())
                    .frame(minWidth: 44, minHeight: 44)
                    .accessibilityLabel(L10n.Settings.editSheetCloseAccessibility)
            }
        }
    }

    private var emailCard: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text(L10n.Settings.emailLabel)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            Text(email)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }
}

#if DEBUG
#Preview("Email") {
    EditEmailSheet(email: "ready.riley@sevino.ai")
        .preferredColorScheme(.dark)
}

#Preview("Missing") {
    EditEmailSheet(email: L10n.Settings.missingValuePlaceholder)
        .preferredColorScheme(.dark)
}
#endif
