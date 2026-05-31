import SwiftUI

struct HomeChatSuggestions: View {
    let scale: CGFloat
    let shortcuts: [Shortcut]
    let hasOverflow: Bool
    let onSelect: (String) -> Void
    let onShowMore: () -> Void

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
                }
            }

            if hasOverflow {
                Button(L10n.Home.shortcutMore, action: onShowMore)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }
}
