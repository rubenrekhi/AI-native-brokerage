import SwiftUI

struct SingleStockCard: View {
    let block: StockCardBlock
    let scale: CGFloat

    @State private var selectedRange: TimeRange
    @State private var scrubValue: String?

    init(block: StockCardBlock, scale: CGFloat) {
        self.block = block
        self.scale = scale
        _selectedRange = State(initialValue: TimeRange(rawValue: block.range) ?? .oneMonth)
    }

    private var currentBars: [Bar] {
        block.bars(for: selectedRange.rawValue)
    }

    private var currentChange: (abs: Double, pct: Double) {
        block.change(for: selectedRange.rawValue)
    }

    private var chartColor: Color {
        let pct = currentChange.pct
        if pct > 0 { return .sevinoPositive }
        if pct < 0 { return .sevinoNegative }
        return .sevinoGreyContrast
    }

    private var chartPoints: [Double] {
        let closes = currentBars.map(\.c)
        guard let lo = closes.min(), let hi = closes.max(), hi > lo else {
            return closes.map { _ in 0.5 }
        }
        let range = hi - lo
        return closes.map { ($0 - lo) / range }
    }

    private var chartValues: [Decimal] {
        currentBars.map { Decimal($0.c) }
    }

    private static let iso8601Fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private var chartDates: [Date] {
        currentBars.map { bar in
            Self.iso8601Fractional.date(from: bar.t)
                ?? Self.iso8601.date(from: bar.t)
                ?? .now
        }
    }

    private var rangeOptions: [TimeRange] {
        block.rangeOptions.compactMap { TimeRange(rawValue: $0) }
    }

    private var formattedPrice: String {
        Decimal(block.price).asCurrency()
    }

    private var formattedChangeAbs: String {
        Decimal(currentChange.abs).asSignedCurrency()
    }

    private var formattedChangePct: String {
        "(\(Decimal(currentChange.pct / 100).asSignedPercent()))"
    }

    private var changePeriodLabel: String {
        selectedRange.periodLabel
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            headerRow
            priceRow
            chartSection
            if rangeOptions.count > 1 {
                rangeSelectorSection
            }
        }
        .padding(16 * scale)
        .background(GenUICardBackground(cornerRadius: 20 * scale))
        .padding(.horizontal, 16 * scale)
    }

    private var headerRow: some View {
        HStack(spacing: 10 * scale) {
            if let logoUrl = block.logoUrl {
                StockLogoView(logoUrl: logoUrl, size: 28 * scale)
            } else {
                StockLogoView(ticker: block.symbol, size: 28 * scale)
            }
            Text(block.symbol)
                .font(.system(size: 15 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
            Text(block.companyName)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoGreyContrast)
                .lineLimit(1)
        }
    }

    private var priceRow: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(scrubValue ?? formattedPrice)
                .font(.system(size: 28 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
                .contentTransition(.numericText())

            HStack(spacing: 4 * scale) {
                Image(systemName: currentChange.pct >= 0 ? "arrow.up.right" : "arrow.down.right")
                    .font(.system(size: 10 * scale, weight: .bold))
                    .foregroundStyle(chartColor)
                    .accessibilityHidden(true)

                HStack(spacing: 2 * scale) {
                    Text(formattedChangeAbs)
                        .font(.system(size: 13 * scale, weight: .medium))
                    Text(formattedChangePct)
                        .font(.system(size: 13 * scale, weight: .medium))
                }
                .foregroundStyle(chartColor)

                Text(changePeriodLabel)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }

    private var chartSection: some View {
        PortfolioChartView(
            points: chartPoints,
            values: chartValues,
            dates: chartDates,
            range: selectedRange,
            color: chartColor,
            animatesRangeChange: false,
            scale: scale,
            scrubValue: $scrubValue
        )
        .frame(height: 120 * scale)
    }

    private var rangeSelectorSection: some View {
        HomeTimeRangeSelector(
            selected: selectedRange,
            options: rangeOptions,
            usesGlass: false,
            scale: scale,
            onSelect: { selectedRange = $0 }
        )
    }
}

#Preview {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        SingleStockCard(
            block: StockCardBlock(
                blockId: "1",
                symbol: "TSLA",
                companyName: "Tesla, Inc.",
                price: 443.30,
                changeAbs: 32.58,
                changePct: 0.08,
                colorState: .positive,
                bars: [
                    Bar(t: "2025-01-01T00:00:00Z", c: 410.0),
                    Bar(t: "2025-02-01T00:00:00Z", c: 395.0),
                    Bar(t: "2025-03-01T00:00:00Z", c: 420.0),
                    Bar(t: "2025-04-01T00:00:00Z", c: 443.3)
                ],
                range: "3M",
                rangeOptions: ["1D", "1W", "1M", "3M", "6M", "1Y"]
            ),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}
