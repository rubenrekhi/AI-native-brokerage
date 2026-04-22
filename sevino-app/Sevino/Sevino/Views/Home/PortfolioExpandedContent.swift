import SwiftUI

/// The expanded-only content (gain text, chart, time selector, chat button).
struct PortfolioExpandedContent: View {
    let scale: CGFloat
    let viewModel: PortfolioViewModel
    @State private var scrubValue: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            Text("\(viewModel.gainText) \(viewModel.periodLabel)")
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoPositive)

            PortfolioChartView(points: viewModel.chartPoints, scale: scale, scrubValue: $scrubValue)
                .frame(height: 160 * scale)

            HomeTimeRangeSelector(
                selected: viewModel.selectedTimeRange,
                scale: scale,
                onSelect: viewModel.setTimeRange
            )

            Button(L10n.Home.chatAboutThis, action: {})
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 20 * scale)
                .padding(.vertical, 12 * scale)
                .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 24 * scale))
        }
        .transition(.opacity.animation(.easeIn(duration: 0.25).delay(0.15)))
    }
}
