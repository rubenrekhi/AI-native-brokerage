import SwiftUI

/// Bottom sheet listing the overflow shortcuts (items 4–13). Tapping a row
/// pre-fills the chat input via `onSelect` and dismisses the sheet; `onSelect`
/// does not auto-send. Presented by `ShortcutsRail` when "More" is tapped.
struct ShortcutsOverflowSheet: View {
    let scale: CGFloat
    let shortcuts: [Shortcut]
    let onSelect: (String) -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                ForEach(shortcuts) { shortcut in
                    Button { select(shortcut) } label: {
                        HStack(spacing: 6 * scale) {
                            Text(shortcut.text)
                                .font(.system(size: 14 * scale))
                                .foregroundStyle(Color.sevinoSecondary)
                            Spacer()
                            Image(systemName: "arrow.down.left")
                                .font(.system(size: 11 * scale, weight: .semibold))
                                .foregroundStyle(Color.sevinoSecondary)
                                .accessibilityHidden(true)
                        }
                    }
                }
            }
            .listStyle(.plain)
            .navigationTitle(L10n.Home.shortcutOverflowTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L10n.General.done) { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    func select(_ shortcut: Shortcut) {
        onSelect(shortcut.text)
        dismiss()
    }
}

#Preview {
    ShortcutsOverflowSheet(
        scale: 1,
        shortcuts: (0..<10).map {
            Shortcut(id: UUID(), text: "Sample question \($0)", category: .capability)
        },
        onSelect: { _ in }
    )
}
