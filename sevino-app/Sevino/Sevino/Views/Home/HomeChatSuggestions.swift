import SwiftUI

struct HomeChatSuggestions: View {
    let scale: CGFloat
    let shortcuts: [Shortcut]
    let canExpand: Bool
    let isExpanded: Bool
    let onSelect: (String) -> Void
    let onToggleExpand: () -> Void

    var body: some View {
        VStack(alignment: .trailing, spacing: 14 * scale) {
            ForEach(shortcuts) { shortcut in
                Button { onSelect(shortcut.text) } label: {
                    HStack(spacing: 6 * scale) {
                        Text(shortcut.text)
                            .font(.system(size: 14 * scale))
                            .foregroundStyle(Color.sevinoSecondary)

                        Image(systemName: "arrow.down.left")
                            .font(.system(size: 11 * scale, weight: .semibold))
                            .foregroundStyle(Color.sevinoSecondary)
                            .accessibilityHidden(true)
                    }
                    .contentShape(.rect)
                }
            }

            if canExpand {
                Button(action: onToggleExpand) {
                    Text(isExpanded
                         ? L10n.Home.shortcutLess
                         : L10n.Home.shortcutMore)
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                        .contentShape(.rect)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }
}
