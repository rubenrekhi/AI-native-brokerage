import SwiftUI

struct ProtectedCardView: View {
    let scale: CGFloat
    @State private var chartProgress: CGFloat = 0

    private static let chartPoints: [CGFloat] = [
        0.20, 0.18, 0.19, 0.17, 0.15, 0.16, 0.14, 0.15, 0.13, 0.12,
        0.14, 0.13, 0.15, 0.14, 0.16, 0.15, 0.17, 0.18, 0.16, 0.19,
        0.20, 0.22, 0.21, 0.24, 0.23, 0.25, 0.28, 0.30, 0.32, 0.35,
        0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.75, 0.80, 0.88, 0.95,
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.Welcome.portfolioLabel)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.welcomeTextMuted)
                .padding(.horizontal, 16 * scale)

            HStack(spacing: 8 * scale) {
                Text(L10n.Welcome.protectedValue)
                    .font(.system(size: 28 * scale, weight: .bold))
                    .foregroundStyle(Color.welcomeText)

                Image(systemName: "lock.fill")
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .accessibilityHidden(true)
            }
            .padding(.top, 4 * scale)
            .padding(.horizontal, 16 * scale)

            AnimatedChartLine(
                points: Self.chartPoints,
                scale: scale,
                height: 120,
                progress: chartProgress
            )
            .padding(.top, 12 * scale)
        }
        .padding(.vertical, 16 * scale)
        .modifier(SevinoGlass.card)
        .onAppear { animateChart() }
    }

    private func animateChart() {
        chartProgress = 0
        withAnimation(.easeOut(duration: 1.5)) {
            chartProgress = 1
        }
    }
}
