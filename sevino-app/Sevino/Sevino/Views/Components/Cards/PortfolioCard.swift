import SwiftUI

struct PortfolioCard: View {
    let data: PortfolioCardData
    let scale: CGFloat
    let isInteractive: Bool
    var onTimeRangeChanged: (TimeRange) -> Void = { _ in }

    @State private var scrubValue: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            HStack(spacing: 8 * scale) {
                Text(data.displayValue)
                    .font(.system(size: 36 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)

                Text(L10n.Home.portfolioCurrency)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }

            VStack(alignment: .leading, spacing: 16 * scale) {
                Text("\(data.gainText) \(data.periodLabel)")
                    .font(.system(size: 15 * scale, weight: .medium))
                    .foregroundStyle(data.isDown ? Color.sevinoNegative : Color.sevinoPositive)

                PortfolioChartView(points: data.chartPoints, scale: scale, scrubValue: $scrubValue)
                    .frame(height: 160 * scale)

                if isInteractive {
                    HomeTimeRangeSelector(
                        selected: data.selectedTimeRange,
                        scale: scale,
                        onSelect: onTimeRangeChanged
                    )
                }
            }
        }
        .padding(16 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }
}

#Preview("Interactive") {
    PortfolioCard(
        data: PortfolioCardData(
            displayValue: "$12,345.67",
            isDown: false,
            gainText: "+$234.56",
            periodLabel: "Past 30 Days",
            chartPoints: (0..<40).map { _ in Double.random(in: 0.1...0.9) },
            selectedTimeRange: .oneMonth
        ),
        scale: 1,
        isInteractive: true,
        onTimeRangeChanged: { _ in }
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Read-only") {
    PortfolioCard(
        data: PortfolioCardData(
            displayValue: "$8,420.10",
            isDown: true,
            gainText: "-$120.44",
            periodLabel: "Past 7 Days",
            chartPoints: (0..<40).map { _ in Double.random(in: 0.1...0.9) },
            selectedTimeRange: .oneWeek
        ),
        scale: 1,
        isInteractive: false
    )
    .padding()
    .background(Color.sevinoPrimary)
}
