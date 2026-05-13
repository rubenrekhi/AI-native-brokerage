import SwiftUI

struct SingleStockCard: View {
    let block: StockCardBlock
    var scale: CGFloat = 1

    @State private var selectedRange: TimeRange
    @State private var scrubValue: String?

    init(block: StockCardBlock, scale: CGFloat = 1) {
        self.block = block
        self.scale = scale
        _selectedRange = State(
            initialValue: TimeRange(rawValue: block.range) ?? .oneMonth
        )
    }

    private var rangeOptions: [TimeRange] {
        block.rangeOptions.compactMap { TimeRange(rawValue: $0) }
    }

    private var rangeChange: (abs: Double, pct: Double) {
        block.change(for: selectedRange.rawValue)
    }

    private var accentColor: Color {
        let change = rangeChange.abs
        if change > 1e-9 { return .sevinoPositive }
        if change < -1e-9 { return .sevinoNegative }
        return .sevinoGreyContrast
    }

    var body: some View {
        let visibleBars = block.bars(for: selectedRange.rawValue)
        let chart = Self.chartInputs(for: visibleBars)
        let change = rangeChange

        return VStack(alignment: .leading, spacing: 16 * scale) {
            StockCardHeader(
                symbol: block.symbol,
                companyName: block.companyName,
                logoUrl: block.logoUrl,
                scale: scale
            )
            StockCardPriceBlock(
                price: block.price,
                changeAbs: change.abs,
                changePct: change.pct,
                accentColor: accentColor,
                scale: scale
            )
            PortfolioChartView(
                points: chart.points,
                values: chart.values,
                dates: chart.dates,
                range: selectedRange,
                color: accentColor,
                animatesRangeChange: false,
                scale: scale,
                scrubValue: $scrubValue
            )
            .frame(height: 140 * scale)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(L10n.Chat.stockCardChartAccessibilityLabel(block.symbol))
            .accessibilityValue(
                L10n.Chat.stockCardChartAccessibilityValue(
                    Self.formatPrice(block.price),
                    selectedRange.periodLabel
                )
            )

            HomeTimeRangeSelector(
                selected: selectedRange,
                options: rangeOptions,
                scale: scale,
                onSelect: { selectedRange = $0 }
            )

            if let stats = block.stats {
                StockCardStatsGrid(stats: stats, scale: scale)
            }
        }
        .padding(16 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }

    // MARK: - Chart inputs

    struct ChartInputs: Equatable {
        let points: [Double]
        let values: [Decimal]
        let dates: [Date]
    }

    /// Build the three parallel arrays `PortfolioChartView` wants from a
    /// single pass over `bars`. Dates bail to `[]` on any parse miss to
    /// preserve `count == points.count` parity — the chart's scrub date
    /// label silently blanks every position otherwise.
    static func chartInputs(for bars: [Bar]) -> ChartInputs {
        let closes = bars.map(\.c)
        let points: [Double]
        if let lo = closes.min(), let hi = closes.max(), hi > lo {
            points = closes.map { ($0 - lo) / (hi - lo) }
        } else {
            // Single-value / all-equal / empty series — center the line
            // so the chart isn't collapsed to the bottom edge.
            points = Array(repeating: 0.5, count: closes.count)
        }

        let values = closes.map { Decimal($0) }
        let parsedDates = bars.map { parseISO8601($0.t) }
        let dates: [Date] = parsedDates.allSatisfy { $0 != nil }
            ? parsedDates.compactMap { $0 }
            : []
        return ChartInputs(points: points, values: values, dates: dates)
    }

    /// Backend may send timestamps with or without fractional seconds;
    /// `ISO8601DateFormatter` is strict so we try both.
    private static func parseISO8601(_ s: String) -> Date? {
        if let date = isoFormatterFractional.date(from: s) { return date }
        return isoFormatter.date(from: s)
    }

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let isoFormatterFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    /// Internal helper for the accessibility value — keeps the price
    /// formatter colocated with the rest of the price wiring so a
    /// future change to currency style only needs one edit.
    fileprivate static func formatPrice(_ price: Double) -> String {
        Decimal(price).formatted(
            .currency(code: "USD").precision(.fractionLength(2))
        )
    }
}

// MARK: - Subviews

private struct StockCardHeader: View {
    let symbol: String
    let companyName: String
    let logoUrl: String?
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            StockLogoView(logoUrl: logoUrl, size: 22 * scale)

            Text(symbol)
                .font(.system(size: 15 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            Text(companyName)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .lineLimit(1)
                .truncationMode(.tail)
        }
    }
}

private struct StockCardPriceBlock: View {
    let price: Double
    let changeAbs: Double
    let changePct: Double
    let accentColor: Color
    let scale: CGFloat

    private var arrowSymbol: String? {
        if changeAbs > 1e-9 { return "arrow.up" }
        if changeAbs < -1e-9 { return "arrow.down" }
        return nil
    }

    private var formattedPrice: String {
        SingleStockCard.formatPrice(price)
    }

    private var formattedChange: String {
        let absDisplay = Decimal(changeAbs).formatted(
            .currency(code: "USD")
                .sign(strategy: .always())
                .precision(.fractionLength(2))
        )
        let pctDisplay = Decimal(changePct).formatted(
            .percent.sign(strategy: .always()).precision(.fractionLength(2))
        )
        return "\(absDisplay) (\(pctDisplay))"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(formattedPrice)
                .font(.system(size: 34 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
                .contentTransition(.numericText())
                .animation(.easeInOut(duration: 0.25), value: price)

            HStack(spacing: 6 * scale) {
                if let arrow = arrowSymbol {
                    Image(systemName: arrow)
                        .font(.system(size: 12 * scale, weight: .semibold))
                        .foregroundStyle(accentColor)
                        .accessibilityHidden(true)
                }

                Text(formattedChange)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(accentColor)
                    .contentTransition(.numericText())
                    .animation(.easeInOut(duration: 0.25), value: changeAbs)
            }
        }
    }
}

private struct StatRow: Identifiable {
    let label: String
    let value: String
    var id: String { label }
}

private struct StockCardStatsGrid: View {
    let stats: StockStats
    let scale: CGFloat

    var body: some View {
        let rows = Self.rows(stats)
        let columnCount = (rows.count + 1) / 2
        let leftRows = Array(rows.prefix(columnCount))
        let rightRows = Array(rows.dropFirst(columnCount))

        HStack(alignment: .top, spacing: 24 * scale) {
            StockCardStatsColumn(rows: leftRows, scale: scale)
            StockCardStatsColumn(rows: rightRows, scale: scale)
        }
    }

    /// Order matters — rows split top/bottom into the two columns so
    /// the most-asked stats (price range, 52w range, volume, market cap)
    /// land on the left.
    static func rows(_ stats: StockStats) -> [StatRow] {
        var rows: [StatRow] = []
        func add(_ label: String, _ value: String?) {
            if let value, !value.isEmpty {
                rows.append(StatRow(label: label, value: value))
            }
        }
        add(L10n.Chat.stockStatOpen, StockCardFormatters.currency(stats.open))
        add(L10n.Chat.stockStatDayHigh, StockCardFormatters.currency(stats.dayHigh))
        add(L10n.Chat.stockStatDayLow, StockCardFormatters.currency(stats.dayLow))
        add(L10n.Chat.stockStatPreviousClose, StockCardFormatters.currency(stats.previousClose))
        add(L10n.Chat.stockStatYearHigh, StockCardFormatters.currency(stats.yearHigh))
        add(L10n.Chat.stockStatYearLow, StockCardFormatters.currency(stats.yearLow))
        add(L10n.Chat.stockStatMarketCap, StockCardFormatters.compactInt(stats.marketCap, currency: true))
        add(L10n.Chat.stockStatVolume, StockCardFormatters.compactInt(stats.volume, currency: false))
        add(L10n.Chat.stockStatAvgVolume, StockCardFormatters.compactInt(stats.avgVolume, currency: false))
        add(L10n.Chat.stockStatPeRatio, StockCardFormatters.decimal(stats.peRatio))
        add(L10n.Chat.stockStatEps, StockCardFormatters.currency(stats.eps))
        add(L10n.Chat.stockStatBeta, StockCardFormatters.decimal(stats.beta))
        add(L10n.Chat.stockStatDividendYield, StockCardFormatters.percent(stats.dividendYield))
        add(L10n.Chat.stockStatExchange, stats.exchange)
        return rows
    }
}

private struct StockCardStatsColumn: View {
    let rows: [StatRow]
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 0) {
            ForEach(rows) { row in
                HStack {
                    Text(row.label)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Spacer()
                    Text(row.value)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                }
                .padding(.vertical, 6 * scale)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Previews

private extension StockCardBlock {
    static func preview(
        colorState: ColorState = .positive,
        bars: [Bar] = StockCardBlock.previewBars,
        range: String = "1M"
    ) -> StockCardBlock {
        StockCardBlock(
            blockId: "blk_card_preview",
            symbol: "AMD",
            companyName: "Advanced Micro Devices Inc.",
            logoUrl: "https://financialmodelingprep.com/image-stock/AMD.png",
            price: 184.92,
            changeAbs: colorState == .negative ? -2.12 : 2.12,
            changePct: colorState == .negative ? -0.0116 : 0.0116,
            colorState: colorState,
            bars: bars,
            range: range,
            rangeOptions: ["1D", "1W", "1M", "3M", "6M", "1Y"]
        )
    }

    static let previewBars: [Bar] = (0..<40).map { i in
        Bar(
            t: "2026-04-29T13:\(String(format: "%02d", i % 60)):00Z",
            c: 180 + Double.random(in: -5...10) + Double(i) * 0.1
        )
    }
}

#Preview("Positive") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        SingleStockCard(block: .preview(colorState: .positive))
            .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Negative") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        SingleStockCard(block: .preview(colorState: .negative))
            .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Neutral / no bars yet") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        SingleStockCard(block: .preview(colorState: .neutral, bars: []))
            .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Light mode") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        SingleStockCard(block: .preview())
            .padding(16)
    }
    .preferredColorScheme(.light)
}
