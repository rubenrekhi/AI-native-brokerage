import Charts
import SwiftUI

/// Chat gen-UI card comparing 2–3 assets side by side: an overlay line chart
/// with crosshair scrub, an asset table, and a metric panel that adapts to the
/// asset-type mix (all-stock, all-ETF, or asymmetric stock-vs-ETF). Display
/// only — the range pills reflect the block's range but don't refetch, since a
/// `StockComparisonBlock` carries a single `series` per asset (SEV-658).
struct StockComparisonCard: View {
    let block: StockComparisonBlock
    let scale: CGFloat

    @State private var scrubDate: Date?

    private static let dash = "—"
    private static let fallbackPalette: [Color] = [.sevinoInfo, .sevinoWarning, .sevinoAvatarPurple]

    var body: some View {
        VStack(alignment: .leading, spacing: 14 * scale) {
            if let narration = block.narration, !narration.isEmpty {
                Text(narration)
                    .font(.system(size: 13 * scale))
                    .italic()
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .fixedSize(horizontal: false, vertical: true)
            }
            chartSection
            if block.availableRanges.count > 1 {
                rangeSelector
            }
            assetTable
            metricSection
            if hasDistinctions {
                distinctionRows
            }
        }
        .padding(16 * scale)
        .background(GenUICardBackground(cornerRadius: 20 * scale))
        .padding(.horizontal, 16 * scale)
    }

    // MARK: - Chart

    private var chartSection: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            scrubHeader
            chart
        }
    }

    private var scrubHeader: some View {
        HStack(spacing: 10 * scale) {
            if let date = scrubDate {
                ForEach(Array(block.assets.enumerated()), id: \.element.id) { index, asset in
                    HStack(spacing: 4 * scale) {
                        Circle()
                            .fill(lineColor(for: asset, index: index))
                            .frame(width: 7 * scale, height: 7 * scale)
                        Text(scrubPrice(at: date, in: asset).asCurrency())
                            .font(.system(size: 12 * scale, weight: .semibold))
                            .foregroundStyle(Color.sevinoSecondary)
                            .lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
                Text(scrubDateLabel(date))
                    .font(.system(size: 11 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .lineLimit(1)
            }
        }
        .frame(height: 16 * scale, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var chart: some View {
        Chart {
            ForEach(assetLines) { line in
                ForEach(line.points) { point in
                    LineMark(
                        x: .value("Time", point.date),
                        y: .value("Change", point.value),
                        series: .value("Asset", line.id)
                    )
                    .foregroundStyle(line.color)
                    .interpolationMethod(.monotone)
                }
            }
            if let date = scrubDate {
                RuleMark(x: .value("Time", date))
                    .foregroundStyle(Color.sevinoGreyContrast.opacity(0.4))
                    .lineStyle(StrokeStyle(lineWidth: 1 * scale))
                ForEach(assetLines) { line in
                    if let point = nearestLinePoint(line.points, to: date) {
                        PointMark(
                            x: .value("Time", point.date),
                            y: .value("Change", point.value)
                        )
                        .foregroundStyle(line.color)
                        .symbolSize(56 * scale)
                    }
                }
            }
        }
        .chartXAxis(.hidden)
        .chartYAxis(.hidden)
        .chartLegend(.hidden)
        .frame(height: 180 * scale)
        .chartOverlay { proxy in
            GeometryReader { geo in
                Rectangle()
                    .fill(.clear)
                    .contentShape(.rect)
                    .gesture(
                        DragGesture(minimumDistance: 0)
                            .onChanged { value in
                                updateScrub(at: value.location, proxy: proxy, geo: geo)
                            }
                            .onEnded { _ in scrubDate = nil }
                    )
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            L10n.Chat.comparisonChartA11y(
                block.assets.map(\.symbol).joined(separator: ", "),
                block.range
            )
        )
    }

    private func updateScrub(at location: CGPoint, proxy: ChartProxy, geo: GeometryProxy) {
        guard let plotFrame = proxy.plotFrame else { return }
        let xInPlot = location.x - geo[plotFrame].origin.x
        guard let date: Date = proxy.value(atX: xInPlot, as: Date.self) else { return }
        scrubDate = referenceDates.min {
            abs($0.timeIntervalSince(date)) < abs($1.timeIntervalSince(date))
        }
    }

    // MARK: - Range selector

    private var rangeSelector: some View {
        HStack(spacing: 0) {
            ForEach(block.availableRanges, id: \.self) { range in
                let isSelected = range == block.range
                Text(range)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(isSelected ? Color.sevinoSecondary : Color.sevinoGreyContrast)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8 * scale)
                    .background {
                        if isSelected {
                            Capsule().fill(Color.sevinoGreyAccent.opacity(0.3))
                        }
                    }
                    .accessibilityLabel(range)
                    .accessibilityAddTraits(isSelected ? [.isSelected] : [])
            }
        }
    }

    // MARK: - Asset table

    private var changeColumnWidth: CGFloat { 78 * scale }
    private var priceColumnWidth: CGFloat { 94 * scale }

    private var assetTable: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8 * scale) {
                Text(L10n.Chat.comparisonColAsset)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(L10n.Chat.comparisonColChange)
                    .frame(width: changeColumnWidth, alignment: .trailing)
                Text(L10n.Chat.comparisonColPrice)
                    .frame(width: priceColumnWidth, alignment: .trailing)
            }
            .font(.system(size: 11 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoGreyContrast)
            .padding(.vertical, 6 * scale)
            .accessibilityHidden(true)

            ForEach(Array(block.assets.enumerated()), id: \.element.id) { index, asset in
                rowDivider
                assetRow(asset, index: index)
            }
        }
    }

    private func assetRow(_ asset: ComparisonAsset, index: Int) -> some View {
        HStack(spacing: 8 * scale) {
            HStack(spacing: 7 * scale) {
                Circle()
                    .fill(lineColor(for: asset, index: index))
                    .frame(width: 12 * scale, height: 12 * scale)
                Text(asset.symbol)
                    .font(.system(size: 14 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Text(asset.changePct.asSignedPercent())
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(changeColor(asset.changePct))
                .frame(width: changeColumnWidth, alignment: .trailing)

            Text(asset.currentPrice.asCurrency())
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(width: priceColumnWidth, alignment: .trailing)
        }
        .padding(.vertical, 7 * scale)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            L10n.Chat.comparisonAssetA11y(
                "\(asset.symbol), \(asset.name)",
                asset.changePct.asSignedPercent(),
                asset.currentPrice.asCurrency()
            )
        )
    }

    // MARK: - Metric panels

    private enum PanelMode { case allStock, allETF, asymmetric }

    private var panelMode: PanelMode {
        let hasStock = block.assets.contains { $0.assetType == .stock }
        let hasETF = block.assets.contains { $0.assetType == .etf }
        if hasStock && hasETF { return .asymmetric }
        if hasETF { return .allETF }
        return .allStock
    }

    @ViewBuilder
    private var metricSection: some View {
        switch panelMode {
        case .allStock: metricGrid(allStockRows)
        case .allETF: allETFPanel
        case .asymmetric: asymmetricPanel
        }
    }

    private var metricLabelWidth: CGFloat { 116 * scale }

    private func metricGrid(_ rows: [MetricRow]) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: 8 * scale) {
                Spacer().frame(width: metricLabelWidth)
                ForEach(Array(block.assets.enumerated()), id: \.element.id) { index, asset in
                    HStack(spacing: 5 * scale) {
                        Circle()
                            .fill(lineColor(for: asset, index: index))
                            .frame(width: 8 * scale, height: 8 * scale)
                        Text(asset.symbol)
                            .font(.system(size: 11 * scale, weight: .semibold))
                            .foregroundStyle(Color.sevinoSecondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }
            .padding(.vertical, 6 * scale)

            ForEach(rows) { row in
                rowDivider
                HStack(spacing: 8 * scale) {
                    Text(row.label)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .frame(width: metricLabelWidth, alignment: .leading)
                    ForEach(Array(zip(block.assets, row.values)), id: \.0.id) { _, value in
                        Text(value)
                            .font(.system(size: 13 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)
                            .frame(maxWidth: .infinity, alignment: .trailing)
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                    }
                }
                .padding(.vertical, 7 * scale)
            }
        }
    }

    private var allStockRows: [MetricRow] {
        [
            MetricRow(id: "pe", label: L10n.Chat.comparisonMetricPe, values: metricValues { numberText($0.peRatio) }),
            MetricRow(id: "mcap", label: L10n.Chat.comparisonMetricMarketCap, values: metricValues { currencyAbbrevText($0.marketCap) }),
            MetricRow(id: "rev", label: L10n.Chat.comparisonMetricRevenueGrowth, values: metricValues { signedPctText($0.revenueGrowthPct) }),
            MetricRow(id: "earn", label: L10n.Chat.comparisonMetricEarningsGrowth, values: metricValues { signedPctText($0.earningsGrowthPct) }),
            MetricRow(id: "beta", label: L10n.Chat.comparisonMetricBeta, values: metricValues { numberText($0.beta) }),
            MetricRow(id: "sector", label: L10n.Chat.comparisonMetricSector, values: metricValues { stringOrDash($0.sector) }),
        ]
    }

    private var allETFPanel: some View {
        VStack(alignment: .leading, spacing: 10 * scale) {
            if let overlap = block.holdingsOverlapPct {
                Text(L10n.Chat.comparisonHoldingsOverlap(overlap.asPercent(maximumFractionDigits: 0)))
                    .font(.system(size: 12 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10 * scale)
                    .padding(.vertical, 7 * scale)
                    .background(Color.sevinoGreyAccent.opacity(0.2), in: .rect(cornerRadius: 8 * scale))
            }
            metricGrid(allETFRows)
            topSectorsBlock
        }
    }

    private var allETFRows: [MetricRow] {
        [
            MetricRow(id: "expense", label: L10n.Chat.comparisonMetricExpenseRatio, values: metricValues { pctText($0.expenseRatioPct) }),
            MetricRow(id: "aum", label: L10n.Chat.comparisonMetricAum, values: metricValues { currencyAbbrevText($0.aum) }),
            MetricRow(id: "yield", label: L10n.Chat.comparisonMetricDividendYield, values: metricValues { pctText($0.dividendYieldPct) }),
            MetricRow(id: "holdings", label: L10n.Chat.comparisonMetricHoldingsCount, values: metricValues { countText($0.holdingsCount) }),
            MetricRow(id: "index", label: L10n.Chat.comparisonMetricIndexTracked, values: metricValues { stringOrDash($0.indexTracked) }),
        ]
    }

    @ViewBuilder
    private var topSectorsBlock: some View {
        let withSectors = block.assets.enumerated().filter {
            !($0.element.metrics.topSectors ?? []).isEmpty
        }
        if !withSectors.isEmpty {
            VStack(alignment: .leading, spacing: 8 * scale) {
                Text(L10n.Chat.comparisonMetricTopSectors)
                    .font(.system(size: 11 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                ForEach(withSectors, id: \.element.id) { index, asset in
                    HStack(spacing: 6 * scale) {
                        Circle()
                            .fill(lineColor(for: asset, index: index))
                            .frame(width: 8 * scale, height: 8 * scale)
                        Text(asset.symbol)
                            .font(.system(size: 12 * scale, weight: .semibold))
                            .foregroundStyle(Color.sevinoSecondary)
                        sectorChips(asset.metrics.topSectors ?? [])
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }

    private var asymmetricPanel: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            HStack(alignment: .top, spacing: 10 * scale) {
                ForEach(Array(block.assets.enumerated()), id: \.element.id) { index, asset in
                    typePanel(
                        asset: asset,
                        index: index,
                        typeLabel: typeLabel(for: asset.assetType),
                        rows: panelRows(for: asset)
                    )
                }
            }
            sectorExposureRow(
                stock: block.assets.first { $0.assetType == .stock },
                etf: block.assets.first { $0.assetType == .etf }
            )
        }
    }

    private func typeLabel(for type: AssetType) -> String {
        switch type {
        case .stock: L10n.Chat.comparisonTypeStock
        case .etf: L10n.Chat.comparisonTypeEtf
        }
    }

    private func panelRows(for asset: ComparisonAsset) -> [MetricRow] {
        switch asset.assetType {
        case .stock: stockPanelRows(asset)
        case .etf: etfPanelRows(asset)
        }
    }

    private func typePanel(asset: ComparisonAsset, index: Int, typeLabel: String, rows: [MetricRow]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6 * scale) {
                Circle()
                    .fill(lineColor(for: asset, index: index))
                    .frame(width: 10 * scale, height: 10 * scale)
                Text(asset.symbol)
                    .font(.system(size: 13 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
                Text(typeLabel)
                    .font(.system(size: 10 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .padding(.horizontal, 5 * scale)
                    .padding(.vertical, 2 * scale)
                    .background(Color.sevinoGreyAccent.opacity(0.3), in: .capsule)
            }
            .padding(.bottom, 8 * scale)

            ForEach(rows) { row in
                HStack(spacing: 6 * scale) {
                    Text(row.label)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                    Spacer(minLength: 4 * scale)
                    Text(row.values.first ?? Self.dash)
                        .font(.system(size: 12 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoSecondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
                .padding(.vertical, 5 * scale)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10 * scale)
        .background(Color.sevinoGreyAccent.opacity(0.12), in: .rect(cornerRadius: 12 * scale))
    }

    private func stockPanelRows(_ asset: ComparisonAsset) -> [MetricRow] {
        [
            MetricRow(id: "pe", label: L10n.Chat.comparisonMetricPe, values: [numberText(asset.metrics.peRatio)]),
            MetricRow(id: "rev", label: L10n.Chat.comparisonMetricRevenueGrowth, values: [signedPctText(asset.metrics.revenueGrowthPct)]),
            MetricRow(id: "beta", label: L10n.Chat.comparisonMetricBeta, values: [numberText(asset.metrics.beta)]),
            MetricRow(id: "sector", label: L10n.Chat.comparisonMetricSector, values: [stringOrDash(asset.metrics.sector)]),
        ]
    }

    private func etfPanelRows(_ asset: ComparisonAsset) -> [MetricRow] {
        [
            MetricRow(id: "expense", label: L10n.Chat.comparisonMetricExpenseRatio, values: [pctText(asset.metrics.expenseRatioPct)]),
            MetricRow(id: "holdings", label: L10n.Chat.comparisonMetricHoldingsCount, values: [countText(asset.metrics.holdingsCount)]),
            MetricRow(id: "yield", label: L10n.Chat.comparisonMetricDividendYield, values: [pctText(asset.metrics.dividendYieldPct)]),
            MetricRow(id: "index", label: L10n.Chat.comparisonMetricIndex, values: [stringOrDash(asset.metrics.indexTracked)]),
        ]
    }

    private func sectorExposureRow(stock: ComparisonAsset?, etf: ComparisonAsset?) -> some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            Text(L10n.Chat.comparisonSectorExposure)
                .font(.system(size: 11 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
            HStack(alignment: .top, spacing: 10 * scale) {
                Group {
                    if let sector = stock?.metrics.sector {
                        Text("\(Decimal(1).asPercent(maximumFractionDigits: 0)) \(sector)")
                            .font(.system(size: 12 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)
                    } else {
                        Text(Self.dash).foregroundStyle(Color.sevinoGreyContrast)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                Group {
                    if let sectors = etf?.metrics.topSectors, !sectors.isEmpty {
                        sectorChips(sectors)
                    } else {
                        Text(Self.dash).foregroundStyle(Color.sevinoGreyContrast)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func sectorChips(_ sectors: [SectorExposure]) -> some View {
        HStack(spacing: 5 * scale) {
            ForEach(sectors.prefix(3)) { sector in
                Text("\(sector.name) \(sector.weightPct.asPercent(maximumFractionDigits: 0))")
                    .font(.system(size: 10 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoSecondary)
                    .padding(.horizontal, 7 * scale)
                    .padding(.vertical, 3 * scale)
                    .background(Color.sevinoGreyAccent.opacity(0.3), in: .capsule)
                    .lineLimit(1)
            }
        }
    }

    // MARK: - Distinction footnotes

    private var hasDistinctions: Bool {
        block.assets.contains { !($0.metrics.oneLineDistinction ?? "").isEmpty }
    }

    private var distinctionRows: some View {
        VStack(alignment: .leading, spacing: 5 * scale) {
            ForEach(Array(block.assets.enumerated()), id: \.element.id) { index, asset in
                if let distinction = asset.metrics.oneLineDistinction, !distinction.isEmpty {
                    HStack(alignment: .top, spacing: 6 * scale) {
                        Circle()
                            .fill(lineColor(for: asset, index: index))
                            .frame(width: 7 * scale, height: 7 * scale)
                            .padding(.top, 4 * scale)
                        Text("\(asset.symbol) — \(distinction)")
                            .font(.system(size: 12 * scale))
                            .italic()
                            .foregroundStyle(Color.sevinoGreyContrast)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    // MARK: - Shared chrome

    private var rowDivider: some View {
        Rectangle()
            .fill(Color.sevinoGreyAccent.opacity(0.25))
            .frame(height: 1)
    }

    // MARK: - Derived data

    private struct MetricRow: Identifiable {
        let id: String
        let label: String
        let values: [String]
    }

    private struct AssetLine: Identifiable {
        let id: String
        let color: Color
        let points: [LinePoint]
    }

    private struct LinePoint: Identifiable {
        let id: Int
        let date: Date
        let value: Double
    }

    private var assetLines: [AssetLine] {
        block.assets.enumerated().map { index, asset in
            let base = asset.series.first?.price
            let points = asset.series.enumerated().map { i, point in
                LinePoint(id: i, date: point.timestamp, value: normalized(point.price, base: base ?? point.price))
            }
            return AssetLine(id: asset.symbol, color: lineColor(for: asset, index: index), points: points)
        }
    }

    private var referenceDates: [Date] {
        let longest = block.assets.max { $0.series.count < $1.series.count }
        return longest?.series.map(\.timestamp) ?? []
    }

    private func nearestLinePoint(_ points: [LinePoint], to date: Date) -> LinePoint? {
        points.min { abs($0.date.timeIntervalSince(date)) < abs($1.date.timeIntervalSince(date)) }
    }

    private func scrubPrice(at date: Date, in asset: ComparisonAsset) -> Decimal {
        asset.series.min {
            abs($0.timestamp.timeIntervalSince(date)) < abs($1.timestamp.timeIntervalSince(date))
        }?.price ?? asset.currentPrice
    }

    /// Lines overlay as percent change from each asset's first point so a
    /// $40 stock and a $400 stock share the same baseline; the scrub label
    /// still reads each asset's true price.
    private func normalized(_ price: Decimal, base: Decimal) -> Double {
        let baseValue = NSDecimalNumber(decimal: base).doubleValue
        guard baseValue != 0 else { return 0 }
        return (NSDecimalNumber(decimal: price).doubleValue / baseValue) - 1
    }

    private func lineColor(for asset: ComparisonAsset, index: Int) -> Color {
        Color(hexString: asset.colorHex) ?? Self.fallbackPalette[index % Self.fallbackPalette.count]
    }

    private func changeColor(_ pct: Decimal) -> Color {
        if pct > 0 { return .sevinoPositive }
        if pct < 0 { return .sevinoNegative }
        return .sevinoGreyContrast
    }

    private static let scrubTimeZone = TimeZone(identifier: "America/New_York") ?? .current

    private func scrubDateLabel(_ date: Date) -> String {
        let tz = Self.scrubTimeZone
        switch block.range {
        case "1D":
            return date.formatted(Date.FormatStyle(timeZone: tz).hour().minute())
        case "1W":
            return date.formatted(Date.FormatStyle(timeZone: tz).weekday(.abbreviated).hour().minute())
        case "1M", "3M":
            return date.formatted(Date.FormatStyle(timeZone: tz).month(.abbreviated).day())
        default:
            return date.formatted(Date.FormatStyle(timeZone: tz).month(.abbreviated).day().year())
        }
    }

    private func metricValues(_ transform: (ComparisonAssetMetrics) -> String) -> [String] {
        block.assets.map { transform($0.metrics) }
    }

    private func numberText(_ value: Decimal?) -> String {
        value.map { $0.asShareCount() } ?? Self.dash
    }

    private func currencyAbbrevText(_ value: Decimal?) -> String {
        value.map { $0.asAbbreviatedCurrency() } ?? Self.dash
    }

    private func signedPctText(_ value: Decimal?) -> String {
        value.map { $0.asSignedPercent() } ?? Self.dash
    }

    private func pctText(_ value: Decimal?) -> String {
        value.map { $0.asPercent(maximumFractionDigits: 2) } ?? Self.dash
    }

    private func stringOrDash(_ value: String?) -> String {
        value ?? Self.dash
    }

    private func countText(_ value: Int?) -> String {
        value.map { "\($0)" } ?? Self.dash
    }
}

// MARK: - Previews

private func comparisonPreviewSeries(_ prices: [Double]) -> [SeriesPoint] {
    let start = Date(timeIntervalSince1970: 1_714_000_000)
    return prices.enumerated().map { index, price in
        SeriesPoint(timestamp: start.addingTimeInterval(Double(index) * 86_400), price: Decimal(price))
    }
}

private let comparisonRanges = ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y"]

private func comparisonPreviewCard(_ block: StockComparisonBlock) -> some View {
    ScrollView {
        StockComparisonCard(block: block, scale: 1)
            .padding(.vertical, 24)
    }
    .background(Color.sevinoPrimary.ignoresSafeArea())
}

#Preview("Stock vs Stock") {
    comparisonPreviewCard(
        StockComparisonBlock(
            blockId: "cmp_stocks",
            assets: [
                ComparisonAsset(
                    symbol: "AAPL", name: "Apple Inc.", assetType: .stock, colorHex: "#5E5CE6",
                    currentPrice: 229.87, changePct: 0.0124,
                    series: comparisonPreviewSeries([210, 213, 209, 217, 221, 219, 225, 229.87]),
                    metrics: ComparisonAssetMetrics(
                        peRatio: 34.2, marketCap: 3_480_000_000_000, revenueGrowthPct: 0.061,
                        earningsGrowthPct: 0.078, beta: 1.21, sector: "Technology",
                        oneLineDistinction: "Services margin keeps expanding."
                    )
                ),
                ComparisonAsset(
                    symbol: "MSFT", name: "Microsoft Corp.", assetType: .stock, colorHex: "#30D158",
                    currentPrice: 430.16, changePct: -0.0042,
                    series: comparisonPreviewSeries([445, 441, 438, 442, 435, 433, 431, 430.16]),
                    metrics: ComparisonAssetMetrics(
                        peRatio: 36.8, marketCap: 3_200_000_000_000, revenueGrowthPct: 0.155,
                        earningsGrowthPct: 0.102, beta: 0.92, sector: "Technology",
                        oneLineDistinction: "Azure remains the growth engine."
                    )
                ),
            ],
            range: "1M",
            availableRanges: comparisonRanges
        )
    )
    .preferredColorScheme(.dark)
}

#Preview("ETF vs ETF") {
    comparisonPreviewCard(
        StockComparisonBlock(
            blockId: "cmp_etfs",
            assets: [
                ComparisonAsset(
                    symbol: "VOO", name: "Vanguard S&P 500 ETF", assetType: .etf, colorHex: "#0A84FF",
                    currentPrice: 512.34, changePct: 0.0031,
                    series: comparisonPreviewSeries([498, 501, 505, 503, 508, 510, 511, 512.34]),
                    metrics: ComparisonAssetMetrics(
                        expenseRatioPct: 0.0003, aum: 1_300_000_000_000, holdingsCount: 503,
                        dividendYieldPct: 0.0131, indexTracked: "S&P 500",
                        topSectors: [
                            SectorExposure(name: "Tech", weightPct: 0.31),
                            SectorExposure(name: "Financials", weightPct: 0.13),
                            SectorExposure(name: "Health", weightPct: 0.12),
                        ],
                        oneLineDistinction: "Pure large-cap S&P 500 exposure."
                    )
                ),
                ComparisonAsset(
                    symbol: "VTI", name: "Vanguard Total Stock Market ETF", assetType: .etf, colorHex: "#FF9F0A",
                    currentPrice: 287.91, changePct: 0.0028,
                    series: comparisonPreviewSeries([279, 281, 284, 283, 285, 286, 287, 287.91]),
                    metrics: ComparisonAssetMetrics(
                        expenseRatioPct: 0.0003, aum: 450_000_000_000, holdingsCount: 3700,
                        dividendYieldPct: 0.0128, indexTracked: "CRSP US Total Market",
                        topSectors: [
                            SectorExposure(name: "Tech", weightPct: 0.29),
                            SectorExposure(name: "Financials", weightPct: 0.13),
                            SectorExposure(name: "Health", weightPct: 0.13),
                        ],
                        oneLineDistinction: "Adds mid- and small-caps for total coverage."
                    )
                ),
            ],
            range: "3M",
            availableRanges: comparisonRanges,
            holdingsOverlapPct: 0.84
        )
    )
    .preferredColorScheme(.dark)
}

#Preview("Asymmetric (NVDA vs SMH)") {
    comparisonPreviewCard(
        StockComparisonBlock(
            blockId: "cmp_mixed",
            assets: [
                ComparisonAsset(
                    symbol: "NVDA", name: "NVIDIA Corp.", assetType: .stock, colorHex: "#5E5CE6",
                    currentPrice: 138.07, changePct: 0.0212,
                    series: comparisonPreviewSeries([120, 124, 128, 126, 131, 134, 137, 138.07]),
                    metrics: ComparisonAssetMetrics(
                        peRatio: 64.5, revenueGrowthPct: 0.94, beta: 1.68, sector: "Technology",
                        oneLineDistinction: "Highest beta, highest growth."
                    )
                ),
                ComparisonAsset(
                    symbol: "SMH", name: "VanEck Semiconductor ETF", assetType: .etf, colorHex: "#FF9F0A",
                    currentPrice: 248.55, changePct: 0.0156,
                    series: comparisonPreviewSeries([232, 236, 240, 238, 243, 245, 247, 248.55]),
                    metrics: ComparisonAssetMetrics(
                        expenseRatioPct: 0.0035, holdingsCount: 25, dividendYieldPct: 0.006,
                        indexTracked: "MVIS US Listed Semiconductor 25",
                        topSectors: [
                            SectorExposure(name: "Semis", weightPct: 0.78),
                            SectorExposure(name: "Equipment", weightPct: 0.18),
                            SectorExposure(name: "Other", weightPct: 0.04),
                        ],
                        oneLineDistinction: "Diversifies single-name risk across 25 chipmakers."
                    )
                ),
            ],
            range: "1M",
            availableRanges: comparisonRanges,
            narration: "NVDA is a single stock; SMH is a semiconductor ETF that holds NVDA alongside 24 peers — so this compares a concentrated bet against diversified exposure."
        )
    )
    .preferredColorScheme(.dark)
}

#Preview("Three stocks") {
    comparisonPreviewCard(
        StockComparisonBlock(
            blockId: "cmp_three",
            assets: [
                ComparisonAsset(
                    symbol: "NVDA", name: "NVIDIA Corp.", assetType: .stock, colorHex: "#5E5CE6",
                    currentPrice: 138.07, changePct: 0.0212,
                    series: comparisonPreviewSeries([120, 124, 128, 126, 131, 134, 137, 138.07]),
                    metrics: ComparisonAssetMetrics(
                        peRatio: 64.5, marketCap: 3_380_000_000_000, revenueGrowthPct: 0.94,
                        earningsGrowthPct: 1.12, beta: 1.68, sector: "Technology",
                        oneLineDistinction: "Datacenter demand still accelerating."
                    )
                ),
                ComparisonAsset(
                    symbol: "AMD", name: "Advanced Micro Devices", assetType: .stock, colorHex: "#30D158",
                    currentPrice: 164.08, changePct: 0.0087,
                    series: comparisonPreviewSeries([150, 152, 149, 156, 159, 161, 163, 164.08]),
                    metrics: ComparisonAssetMetrics(
                        peRatio: 47.3, marketCap: 265_000_000_000, revenueGrowthPct: 0.18,
                        earningsGrowthPct: 0.31, beta: 1.74, sector: "Technology",
                        oneLineDistinction: "Closing the datacenter gap on NVDA."
                    )
                ),
                ComparisonAsset(
                    symbol: "INTC", name: "Intel Corp.", assetType: .stock, colorHex: "#FF453A",
                    currentPrice: 23.41, changePct: -0.0153,
                    series: comparisonPreviewSeries([26, 25.4, 25.1, 24.6, 24.2, 23.9, 23.6, 23.41]),
                    metrics: ComparisonAssetMetrics(
                        peRatio: nil, marketCap: 100_000_000_000, revenueGrowthPct: -0.03,
                        earningsGrowthPct: -0.41, beta: 1.05, sector: "Technology",
                        oneLineDistinction: "Turnaround still unproven."
                    )
                ),
            ],
            range: "1M",
            availableRanges: comparisonRanges
        )
    )
    .preferredColorScheme(.dark)
}
