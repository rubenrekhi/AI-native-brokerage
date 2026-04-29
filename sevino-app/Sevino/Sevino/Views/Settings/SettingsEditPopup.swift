import SwiftUI

/// Bottom-anchored popup card used by every editable settings field. Renders
/// an inline `Cancel · Title · Save` header followed by the content slot.
/// Presented via the `popupCard` modifier, which supplies a `popupDismiss`
/// closure in the environment for the inline Cancel button + the post-save
/// auto-dismiss in each edit sheet.
struct SettingsEditPopup<Content: View>: View {
    let title: String
    let scale: CGFloat
    /// When `nil`, the trailing slot is empty (read-only popup with Cancel only).
    let saveAction: SaveAction?
    @ViewBuilder let content: () -> Content

    struct SaveAction {
        let label: String
        let isEnabled: Bool
        let isLoading: Bool
        let perform: () -> Void
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            header
            content()
        }
        .padding(.horizontal, 20 * scale)
        .padding(.top, 16 * scale)
        .padding(.bottom, 48 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .modifier(SevinoGlass.bottomPopup)
    }

    private var header: some View {
        ZStack {
            Text(title)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
                .lineLimit(1)
                // Reserve room for the Cancel/Save buttons so a long centered
                // title can't extend into either button's tap area.
                .padding(.horizontal, 88 * scale)
                .frame(maxWidth: .infinity, alignment: .center)

            HStack {
                CancelButton(scale: scale)

                Spacer()

                if let saveAction {
                    saveButton(saveAction)
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func saveButton(_ action: SaveAction) -> some View {
        Button(action: action.perform) {
            ZStack {
                Text(action.label)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(action.isEnabled ? Color.sevinoPositive : Color.sevinoGreyContrast)
                    .opacity(action.isLoading ? 0 : 1)
                if action.isLoading {
                    ProgressView()
                        .tint(Color.sevinoPositive)
                }
            }
            .contentShape(Rectangle())
            .frame(minHeight: 44, alignment: .trailing)
            .fixedSize(horizontal: true, vertical: false)
        }
        .disabled(!action.isEnabled || action.isLoading)
    }
}

/// Inline cancel button — pulls the dismiss closure from the environment so
/// the popup overlay can close without threading a closure through every
/// caller. `\.dismiss` would dismiss the parent navigation screen instead.
private struct CancelButton: View {
    @Environment(\.popupDismiss) private var popupDismiss

    let scale: CGFloat

    var body: some View {
        Button(L10n.Settings.editProfileCancel) { popupDismiss() }
            .font(.system(size: 15 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(minWidth: 44, minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
    }
}

private struct PopupDismissKey: EnvironmentKey {
    static let defaultValue: () -> Void = {}
}

extension EnvironmentValues {
    var popupDismiss: () -> Void {
        get { self[PopupDismissKey.self] }
        set { self[PopupDismissKey.self] = newValue }
    }
}

/// Section label + content row used inside the popup body. Mirrors the
/// uppercase label / value layout shown in the SEV-454 designs.
struct SettingsEditPopupSection<Content: View>: View {
    let label: String
    let scale: CGFloat
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(label)
                .font(.system(size: 11 * scale, weight: .semibold))
                .tracking(0.5)
                .textCase(.uppercase)
                .foregroundStyle(Color.sevinoGreyContrast)

            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Helper text rendered under the editable area.
struct SettingsEditPopupHelperText: View {
    let text: String
    let scale: CGFloat

    var body: some View {
        Text(text)
            .font(.system(size: 12 * scale))
            .foregroundStyle(Color.sevinoGreyContrast)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Read-only value display used inside `SettingsEditPopupSection`.
struct SettingsEditPopupReadOnlyValue: View {
    let value: String
    let scale: CGFloat

    var body: some View {
        Text(value)
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 12 * scale)
            .textSelection(.enabled)
    }
}

/// Presents an edit popup as a bottom-anchored overlay over the parent view.
/// Used in place of `.sheet(item:)` so the iOS 26 Liquid Glass surface blurs
/// the actual underlying content instead of the system sheet's dim layer.
extension View {
    func popupCard<Item: Identifiable, PopupContent: View>(
        item: Binding<Item?>,
        @ViewBuilder content: @escaping (Item) -> PopupContent
    ) -> some View {
        modifier(PopupCardModifier(item: item, popupContent: content))
    }

    func popupCard<PopupContent: View>(
        isPresented: Binding<Bool>,
        @ViewBuilder content: @escaping () -> PopupContent
    ) -> some View {
        let item = Binding<PopupCardFlag?>(
            get: { isPresented.wrappedValue ? .shown : nil },
            set: { isPresented.wrappedValue = ($0 != nil) }
        )
        return modifier(PopupCardModifier(item: item, popupContent: { _ in content() }))
    }
}

private enum PopupCardFlag: Identifiable {
    case shown
    var id: Self { self }
}

private struct PopupCardModifier<Item: Identifiable, PopupContent: View>: ViewModifier {
    @Binding var item: Item?
    @ViewBuilder let popupContent: (Item) -> PopupContent

    func body(content: Content) -> some View {
        content
            .overlay {
                ZStack(alignment: .bottom) {
                    if let value = item {
                        Color.black.opacity(0.25)
                            .contentShape(Rectangle())
                            .onTapGesture { item = nil }
                            .ignoresSafeArea()
                            .transition(.opacity)
                            .accessibilityHidden(true)

                        popupContent(value)
                            .environment(\.popupDismiss, { item = nil })
                            .transition(.move(edge: .bottom))
                            .accessibilityAction(.escape) { item = nil }
                    }
                }
                // Extend the popup card behind the home indicator. Only the
                // `.container` region is ignored, so SwiftUI's `.keyboard`
                // avoidance still lifts the popup when a TextField is
                // focused.
                .ignoresSafeArea(.container, edges: .bottom)
                .animation(.spring(response: 0.35, dampingFraction: 0.85), value: item?.id)
            }
    }
}

#if DEBUG
#Preview("Editable popup") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            SettingsEditPopup(
                title: "Edit phone",
                scale: 1,
                saveAction: .init(
                    label: L10n.Settings.editProfileSave,
                    isEnabled: true,
                    isLoading: false,
                    perform: {}
                )
            ) {
                SettingsEditPopupSection(label: "mobile number", scale: 1) {
                    SettingsEditPopupReadOnlyValue(value: "+1 (415) 555-0192", scale: 1)
                }
                SettingsEditPopupHelperText(
                    text: "Used for two-factor authentication and trade alerts.",
                    scale: 1
                )
            }
        }
        .preferredColorScheme(.dark)
}

#Preview("Read-only popup") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            SettingsEditPopup(
                title: "Edit email",
                scale: 1,
                saveAction: nil
            ) {
                SettingsEditPopupSection(label: "email address", scale: 1) {
                    SettingsEditPopupReadOnlyValue(value: "ready.riley@sevino.ai", scale: 1)
                }
                SettingsEditPopupHelperText(
                    text: L10n.Settings.editEmailExplanation,
                    scale: 1
                )
            }
        }
        .preferredColorScheme(.dark)
}
#endif
