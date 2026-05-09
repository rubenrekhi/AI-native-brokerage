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
                Group {
                    if data.hasLoaded {
                        Text(data.equity.asCurrency(currencyCode: data.currency))
                    } else {
                        Text(verbatim: "—")
                    }
                }
                .font(.system(size: 36 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

                Text(L10n.Home.portfolioCurrency)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }

            VStack(alignment: .leading, spacing: 16 * scale) {
                Text(data.hasLoaded
                     ? L10n.Home.portfolioGainText(
                         data.gainAbs.asSignedCurrency(currencyCode: data.currency),
                         data.gainPct.asSignedPercent(),
                         data.selectedTimeRange.periodLabel
                       )
                     : "")
                    .font(.system(size: 15 * scale, weight: .medium))
                    .foregroundStyle(data.gainAbs < 0 ? Color.sevinoNegative : Color.sevinoPositive)

                PortfolioChartView(
                    points: data.chartPoints,
                    values: data.chartValues,
                    dates: data.chartDates,
                    currency: data.currency,
                    range: data.selectedTimeRange,
                    scale: scale,
                    scrubValue: $scrubValue
                )
                .frame(height: 160 * scale)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(L10n.Home.portfolioChartAccessibilityLabel)
                .accessibilityValue(
                    L10n.Home.portfolioChartAccessibilityValue(
                        data.equity.asCurrency(currencyCode: data.currency),
                        data.selectedTimeRange.periodLabel
                    )
                )

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
    let now = Date()
    PortfolioCard(
        data: PortfolioCardData(
            equity: Decimal(string: "12345.67")!,
            currency: "USD",
            gainAbs: Decimal(string: "234.56")!,
            gainPct: Decimal(string: "0.0193")!,
            chartPoints: (0..<40).map { _ in Double.random(in: 0.1...0.9) },
            chartValues: (0..<40).map { _ in Decimal(Double.random(in: 11000...13000)) },
            chartDates: (0..<40).map { now.addingTimeInterval(TimeInterval(-($0 * 86400))) }.reversed(),
            selectedTimeRange: .oneMonth,
            hasLoaded: true
        ),
        scale: 1,
        isInteractive: true,
        onTimeRangeChanged: { _ in }
    )
    .padding()
    .background(Color.sevinoPrimary)
}

#Preview("Read-only") {
    let now = Date()
    PortfolioCard(
        data: PortfolioCardData(
            equity: Decimal(string: "8420.10")!,
            currency: "USD",
            gainAbs: Decimal(string: "-120.44")!,
            gainPct: Decimal(string: "-0.0140")!,
            chartPoints: (0..<40).map { _ in Double.random(in: 0.1...0.9) },
            chartValues: (0..<40).map { _ in Decimal(Double.random(in: 8000...8800)) },
            chartDates: (0..<40).map { now.addingTimeInterval(TimeInterval(-($0 * 3600))) }.reversed(),
            selectedTimeRange: .oneWeek,
            hasLoaded: true
        ),
        scale: 1,
        isInteractive: false
    )
    .padding()
    .background(Color.sevinoPrimary)
}
