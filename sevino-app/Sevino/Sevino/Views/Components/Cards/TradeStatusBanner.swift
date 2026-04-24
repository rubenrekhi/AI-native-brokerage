import SwiftUI

/// Full-width colored banner used by MCP trade cards to report success/failure states.
struct TradeStatusBanner: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let text: String
    let systemImage: String?
    let color: Color
    let scale: CGFloat

    @State private var iconBounce: CGFloat = 0.7

    var body: some View {
        HStack(spacing: 8 * scale) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.body.weight(.semibold))
                    .scaleEffect(iconBounce)
            }
            Text(text)
                .font(.body.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 38 * scale)
        .background(
            RoundedRectangle(cornerRadius: 14 * scale)
                .fill(color)
        )
        .transition(
            .scale(scale: 0.92).combined(with: .opacity)
        )
        .onAppear {
            guard !reduceMotion else {
                iconBounce = 1
                return
            }
            withAnimation(.spring(duration: 0.5, bounce: 0.35).delay(0.05)) {
                iconBounce = 1
            }
        }
    }
}

#Preview {
    VStack(spacing: 16) {
        TradeStatusBanner(
            text: "Order submitted",
            systemImage: "checkmark",
            color: .sevinoPositive,
            scale: 1
        )
        TradeStatusBanner(
            text: "Error submitting order",
            systemImage: nil,
            color: .sevinoNegative,
            scale: 1
        )
    }
    .padding()
    .background(Color.sevinoPrimary)
}
