import SwiftUI

struct UserBubbleView: View {
    let text: String
    let scale: CGFloat

    var body: some View {
        Text(text)
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.sevinoSecondary)
            .padding(.horizontal, 14 * scale)
            .padding(.vertical, 10 * scale)
            .background(ChatBubbleBackground(cornerRadius: 20 * scale))
            .frame(maxWidth: 280 * scale, alignment: .trailing)
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.horizontal, 16 * scale)
    }
}

#Preview("Dark") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        VStack(spacing: 16) {
            UserBubbleView(text: "How was Tesla's most recent earnings report?", scale: 1)
            UserBubbleView(text: "Short question", scale: 1)
        }
    }
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        VStack(spacing: 16) {
            UserBubbleView(text: "How was Tesla's most recent earnings report?", scale: 1)
            UserBubbleView(text: "Short question", scale: 1)
        }
    }
    .preferredColorScheme(.light)
}
