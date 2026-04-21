import SwiftUI

struct HomeChatInputBar: View {
    @Binding var text: String
    let scale: CGFloat
    @FocusState private var isFocused: Bool

    private var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            TextField(L10n.Home.chatPlaceholder, text: $text, axis: .vertical)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .lineLimit(1...5)
                .focused($isFocused)
                .padding(.horizontal, 16 * scale)
                .padding(.top, 14 * scale)
                .padding(.bottom, 8 * scale)

            HStack(spacing: 0) {
                Button(L10n.Home.attachAccessibility, systemImage: "plus", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Spacer()

                Button(L10n.Home.micAccessibility, systemImage: "mic", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Button(L10n.Home.sendAccessibility, systemImage: "arrow.up", action: {})
                    .labelStyle(.iconOnly)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(hasText ? Color.sevinoPrimary : Color.sevinoGreyAccent)
                    .frame(width: 30 * scale, height: 30 * scale)
                    .background(hasText ? Color.homeSendActiveBg : .clear, in: .circle)
                    .frame(width: 44 * scale, height: 44 * scale)
            }
            .padding(.horizontal, 4 * scale)
            .padding(.bottom, 4 * scale)
        }
        .modifier(SevinoGlass.card)
    }
}
