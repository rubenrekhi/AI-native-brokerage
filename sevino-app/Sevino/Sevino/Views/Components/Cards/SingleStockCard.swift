import SwiftUI

struct SingleStockCard: View {
    let data: SingleStockCardData
    let scale: CGFloat
    let isInteractive: Bool
    var onTimeRangeChanged: (TimeRange) -> Void = { _ in }

    @State private var scrubValue: String?

    private var changeColor: Color {
        data.isPositive ? Color.sevinoPositive : Color.sevinoNegative
    }

    private var arrow: String {
        data.isPositive ? "arrow.up" : "arrow.down"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            header
            priceBlock
            PortfolioChartView(points: data.chartPoints, scale: scale, scrubValue: $scrubValue)
                .frame(height: 140 * scale)

            HomeTimeRangeSelector(
                selected: data.selectedTimeRange,
                scale: scale,
                onSelect: onTimeRangeChanged
            )
            .allowsHitTesting(isInteractive)

            if let stats = data.stats {
                statsTable(stats)
            }
        }
        .padding(16 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(SevinoGlass.card)
        .clipShape(.rect(cornerRadius: CardGlass.cornerRadius))
    }

    private var header: some View {
        HStack(spacing: 8 * scale) {
            StockLogoView(ticker: data.ticker, size: 22 * scale)

            Text(data.ticker)
                .font(.system(size: 15 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            Text(data.companyName)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .lineLimit(1)
                .truncationMode(.tail)
        }
    }

    private var priceBlock: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(data.price)
                .font(.system(size: 34 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)

            HStack(spacing: 6 * scale) {
                Image(systemName: arrow)
                    .font(.system(size: 12 * scale, weight: .semibold))
                    .foregroundStyle(changeColor)
                    .accessibilityHidden(true)

                Text(data.gainLossText)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(changeColor)

                Text(data.periodLabel)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
    }

    private func statsTable(_ stats: StockStats) -> some View {
        HStack(alignment: .top, spacing: 24 * scale) {
            statsColumn(rows: [
                StatRow(label: L10n.Home.stockStatBid, value: stats.bid),
                StatRow(label: L10n.Home.stockStatAsk, value: stats.ask),
                StatRow(label: L10n.Home.stockStatLastSale, value: stats.lastSale),
                StatRow(label: L10n.Home.stockStatOpen, value: stats.open),
                StatRow(label: L10n.Home.stockStatHigh, value: stats.high),
                StatRow(label: L10n.Home.stockStatLow, value: stats.low),
                StatRow(label: L10n.Home.stockStatExchange, value: stats.exchange),
            ])

            statsColumn(rows: [
                StatRow(label: L10n.Home.stockStatMarketCap, value: stats.marketCap),
                StatRow(label: L10n.Home.stockStatPeRatio, value: stats.peRatio),
                StatRow(label: L10n.Home.stockStatFiftyTwoWeekHigh, value: stats.fiftyTwoWeekHigh),
                StatRow(label: L10n.Home.stockStatFiftyTwoWeekLow, value: stats.fiftyTwoWeekLow),
                StatRow(label: L10n.Home.stockStatVolume, value: stats.volume),
                StatRow(label: L10n.Home.stockStatAvgVolume, value: stats.avgVolume),
                StatRow(label: L10n.Home.stockStatMarginReq, value: stats.marginReq),
            ])
        }
    }

    private func statsColumn(rows: [StatRow]) -> some View {
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

    private struct StatRow: Identifiable {
        let label: String
        let value: String
        var id: String { label }
    }
}

private extension SingleStockCardData {
    static let previewCompact = SingleStockCardData(
        ticker: "AMD",
        companyName: "Advanced Micro Devices Inc.",
        price: "$184.92",
        gainLossText: "$2.12 (0.53%)",
        isPositive: true,
        periodLabel: "Past 30 Days",
        chartPoints: (0..<40).map { _ in Double.random(in: 0.2...0.9) },
        selectedTimeRange: .oneMonth,
        stats: nil
    )

    static let previewExpanded = SingleStockCardData(
        ticker: "AMD",
        companyName: "Advanced Micro Devices Inc.",
        price: "$184.92",
        gainLossText: "$2.12 (0.53%)",
        isPositive: true,
        periodLabel: "Today",
        chartPoints: (0..<40).map { _ in Double.random(in: 0.2...0.9) },
        selectedTimeRange: .oneMonth,
        stats: StockStats(
            bid: "123.25",
            ask: "432.52",
            lastSale: "234.25",
            open: "234.25",
            high: "642.54",
            low: "248.14",
            exchange: "NASDAQ",
            marketCap: "12B",
            peRatio: "23.31",
            fiftyTwoWeekHigh: "234.24",
            fiftyTwoWeekLow: "125.36",
            volume: "341.24K",
            avgVolume: "75.35K",
            marginReq: "20.00%"
        )
    )
}

#Preview("Compact") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        SingleStockCard(
            data: .previewCompact,
            scale: 1,
            isInteractive: true,
            onTimeRangeChanged: { _ in }
        )
        .padding(16)
    }
    .preferredColorScheme(.dark)
}

#Preview("Expanded") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ScrollView {
            SingleStockCard(
                data: .previewExpanded,
                scale: 1,
                isInteractive: true,
                onTimeRangeChanged: { _ in }
            )
            .padding(16)
        }
    }
    .preferredColorScheme(.dark)
}

#Preview("Read-only (MCP)") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        ScrollView {
            VStack(spacing: 16) {
                SingleStockCard(data: .previewCompact, scale: 1, isInteractive: false)
                SingleStockCard(data: .previewExpanded, scale: 1, isInteractive: false)
            }
            .padding(16)
        }
    }
    .preferredColorScheme(.dark)
}
