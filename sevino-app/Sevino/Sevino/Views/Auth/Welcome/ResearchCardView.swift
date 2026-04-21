import SwiftUI

struct ResearchCardView: View {
    let scale: CGFloat
    @State private var cursorVisible = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                Text(L10n.Welcome.researchQuery)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeText)

                Rectangle()
                    .fill(Color.welcomeText)
                    .frame(width: 2 * scale, height: 20 * scale)
                    .opacity(cursorVisible ? 1 : 0)
                    .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: cursorVisible)
                    .onAppear { cursorVisible = false }
            }
            .padding(.horizontal, 12 * scale)
            .padding(.top, 12 * scale)
            .padding(.bottom, 14 * scale)

            HStack(spacing: 0) {
                Image(systemName: "plus")
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(width: 36 * scale, height: 36 * scale)
                    .accessibilityHidden(true)

                Spacer()

                Image(systemName: "mic.fill")
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(width: 36 * scale, height: 36 * scale)
                    .accessibilityHidden(true)

                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28 * scale))
                    .foregroundStyle(Color.welcomeTextSecondary)
                    .frame(width: 36 * scale, height: 36 * scale)
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 6 * scale)
            .padding(.vertical, 6 * scale)
        }
        .padding(.horizontal, 4 * scale)
        .modifier(SevinoGlass.card)
    }
}
