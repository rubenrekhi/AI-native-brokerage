import SwiftUI

struct PeekCardView: View {
    let scale: CGFloat
    let cardCount: Int
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 12 * scale) {
                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(L10n.Digest.title)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)

                    Text(L10n.Digest.cardsReady(cardCount))
                        .font(.system(size: 13 * scale, weight: .regular))
                        .foregroundStyle(Color.sevinoSecondary.opacity(0.62))
                }

                Spacer()

                Image(systemName: "chevron.up")
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary.opacity(0.72))
                    .frame(width: 34 * scale, height: 34 * scale)
                    .background(Color.sevinoSecondary.opacity(0.08), in: .circle)
            }
            .padding(.horizontal, 18 * scale)
            .padding(.vertical, 14 * scale)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.card)
        .accessibilityLabel(L10n.Digest.title)
        .accessibilityIdentifier("digest.peek")
    }
}

#Preview {
    PeekCardView(scale: 1, cardCount: 4, onTap: {})
        .padding()
        .background(Color.sevinoPrimary)
}
