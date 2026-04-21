import SwiftUI

struct PortfolioCardView: View {
    let scale: CGFloat
    @State private var chartProgress: CGFloat = 0

    private static let chartPoints: [CGFloat] = [
        0.45, 0.42, 0.40, 0.38, 0.35, 0.33, 0.30, 0.32, 0.28, 0.25,
        0.27, 0.30, 0.28, 0.32, 0.35, 0.33, 0.36, 0.40, 0.38, 0.42,
        0.45, 0.50, 0.55, 0.52, 0.58, 0.55, 0.60, 0.65, 0.70, 0.68,
        0.72, 0.78, 0.82, 0.85, 0.80, 0.88, 0.92, 0.95, 0.90, 0.98,
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.Welcome.portfolioLabel)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.welcomeTextMuted)
                .padding(.horizontal, 16 * scale)

            HStack(spacing: 8 * scale) {
                Text(L10n.Welcome.portfolioValue)
                    .font(.system(size: 28 * scale, weight: .bold))
                    .foregroundStyle(Color.welcomeText)

                Text(L10n.Welcome.portfolioGain)
                    .font(.system(size: 14 * scale, weight: .semibold))
                    .foregroundStyle(Color.welcomeText)
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

            TimeframeTabsView(scale: scale, selected: .threeMonths)
                .padding(.top, 12 * scale)
                .padding(.horizontal, 8 * scale)
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
