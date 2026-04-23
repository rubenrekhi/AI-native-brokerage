import SwiftUI

/// Liquid glass popup that displays ticker search results above the chat input.
///
/// Pure presentation component — parent controls visibility (hide when `results` is empty)
/// and positioning. Each row shows a logo, bold ticker symbol, and secondary company name.
/// Tapping a row invokes `onSelect` with the chosen result.
struct TickerMentionPopup: View {
    let results: [AssetSearchResult]
    let onSelect: (AssetSearchResult) -> Void

    @State private var scale: CGFloat = 1

    private static let rowHeight: CGFloat = 56
    private static let maxVisibleRows = 5
    private static let logoSize: CGFloat = 24
    private static let horizontalPadding: CGFloat = 16
    private static let verticalPadding: CGFloat = 8
    private static let logoTrailingSpacing: CGFloat = 12
    private static let verticalTextSpacing: CGFloat = 2

    private var contentHeight: CGFloat {
        let rows = min(results.count, Self.maxVisibleRows)
        let rowsHeight = Self.rowHeight * CGFloat(rows)
        let padding = Self.verticalPadding * 2
        return (rowsHeight + padding) * scale
    }

    var body: some View {
        SevinoGlassContainer {
            ScrollView {
                LazyVStack(spacing: 0) {
                    Color.clear.frame(height: Self.verticalPadding * scale)
                    ForEach(results) { result in
                        Button {
                            onSelect(result)
                        } label: {
                            row(for: result)
                        }
                        .buttonStyle(.plain)
                        .contentShape(.rect)

                        if result.id != results.last?.id {
                            Divider()
                                .padding(
                                    .leading,
                                    (Self.horizontalPadding + Self.logoSize + Self.logoTrailingSpacing) * scale
                                )
                        }
                    }
                    Color.clear.frame(height: Self.verticalPadding * scale)
                }
            }
            .scrollBounceBehavior(.basedOnSize)
            .frame(height: contentHeight)
            .modifier(SevinoGlass.popup)
        }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    scale = geo.size.width / 393
                }
            }
        }
    }

    private func row(for result: AssetSearchResult) -> some View {
        HStack(spacing: Self.logoTrailingSpacing * scale) {
            StockLogoView(logoUrl: result.logoUrl, size: Self.logoSize * scale)

            VStack(alignment: .leading, spacing: Self.verticalTextSpacing * scale) {
                Text(result.symbol)
                    .font(.body)
                    .bold()
                    .foregroundStyle(Color.sevinoSecondary)

                Text(result.name)
                    .font(.subheadline)
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .lineLimit(1)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Self.horizontalPadding * scale)
        .frame(height: Self.rowHeight * scale)
        .contentShape(.rect)
    }
}

#Preview("Five results") {
    TickerMentionPopup(
        results: [
            AssetSearchResult(symbol: "AAPL", name: "Apple Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/AAPL.png"),
            AssetSearchResult(symbol: "TSLA", name: "Tesla, Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/TSLA.png"),
            AssetSearchResult(symbol: "NVDA", name: "NVIDIA Corporation", logoUrl: "https://financialmodelingprep.com/image-stock/NVDA.png"),
            AssetSearchResult(symbol: "AMD", name: "Advanced Micro Devices, Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/AMD.png"),
            AssetSearchResult(symbol: "MSFT", name: "Microsoft Corporation", logoUrl: "https://financialmodelingprep.com/image-stock/MSFT.png"),
        ],
        onSelect: { _ in }
    )
    .padding()
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.sevinoPrimary)
}

#Preview("Single result") {
    TickerMentionPopup(
        results: [
            AssetSearchResult(symbol: "AAPL", name: "Apple Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/AAPL.png"),
        ],
        onSelect: { _ in }
    )
    .padding()
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.sevinoPrimary)
}

#Preview("Overflowing (scrollable)") {
    TickerMentionPopup(
        results: [
            AssetSearchResult(symbol: "AAPL", name: "Apple Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/AAPL.png"),
            AssetSearchResult(symbol: "TSLA", name: "Tesla, Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/TSLA.png"),
            AssetSearchResult(symbol: "NVDA", name: "NVIDIA Corporation", logoUrl: "https://financialmodelingprep.com/image-stock/NVDA.png"),
            AssetSearchResult(symbol: "AMD", name: "Advanced Micro Devices, Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/AMD.png"),
            AssetSearchResult(symbol: "MSFT", name: "Microsoft Corporation", logoUrl: "https://financialmodelingprep.com/image-stock/MSFT.png"),
            AssetSearchResult(symbol: "GOOGL", name: "Alphabet Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/GOOGL.png"),
            AssetSearchResult(symbol: "AMZN", name: "Amazon.com, Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/AMZN.png"),
            AssetSearchResult(symbol: "META", name: "Meta Platforms, Inc.", logoUrl: "https://financialmodelingprep.com/image-stock/META.png"),
        ],
        onSelect: { _ in }
    )
    .padding()
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(Color.sevinoPrimary)
}
