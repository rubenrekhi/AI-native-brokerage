import SwiftUI

struct HomeChatSuggestions: View {
    let scale: CGFloat
    let onSelect: (String) -> Void

    private static let suggestions: [String] = [
        L10n.Home.suggestionNews,
        L10n.Home.suggestionPortfolio,
        L10n.Home.suggestionRadar,
    ]

    var body: some View {
        VStack(alignment: .trailing, spacing: 14 * scale) {
            ForEach(Self.suggestions, id: \.self) { suggestion in
                Button { onSelect(stripped(suggestion)) } label: {
                    HStack(spacing: 6 * scale) {
                        Text(suggestion)
                            .font(.system(size: 14 * scale))
                            .foregroundStyle(Color.homeSendActiveBg)

                        Image(systemName: "arrow.down.left")
                            .font(.system(size: 11 * scale, weight: .semibold))
                            .foregroundStyle(Color.homeSendActiveBg)
                            .accessibilityHidden(true)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }

    private func stripped(_ text: String) -> String {
        text.trimmingCharacters(in: CharacterSet(charactersIn: "\u{201C}\u{201D}\""))
    }
}
