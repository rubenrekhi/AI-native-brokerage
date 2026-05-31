import SwiftUI

struct PendingOrdersCardView: View {
    let card: PendingOrderActivityDigestCard
    let scale: CGFloat

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16 * scale) {
                orderSection(title: L10n.Digest.pendingFilledTitle, emptyText: L10n.Digest.pendingFilledEmpty, items: card.filled)
                orderSection(title: L10n.Digest.pendingRecurringExecutedTitle, emptyText: L10n.Digest.pendingRecurringExecutedEmpty, items: card.recurringExecuted)
                orderSection(title: L10n.Digest.pendingRecurringSkippedTitle, emptyText: L10n.Digest.pendingRecurringSkippedEmpty, items: card.recurringSkipped)
            }
        }
        .scrollIndicators(.hidden)
    }

    private func orderSection(title: String, emptyText: String, items: [OrderActivityItemDTO]) -> some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(title)
                .font(.system(size: 14 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoPrimary)

            if items.isEmpty {
                Text(emptyText)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.56))
                    .padding(.vertical, 8 * scale)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                        orderRow(item)
                        if index < items.count - 1 {
                            Divider().background(Color.sevinoPrimary.opacity(0.12))
                        }
                    }
                }
            }
        }
        .padding(12 * scale)
        .background(Color.sevinoPrimary.opacity(0.05), in: .rect(cornerRadius: 8 * scale))
    }

    private func orderRow(_ item: OrderActivityItemDTO) -> some View {
        HStack(alignment: .center, spacing: 10 * scale) {
            StockLogoView(ticker: item.symbol, size: 28 * scale)

            VStack(alignment: .leading, spacing: 3 * scale) {
                HStack(spacing: 6 * scale) {
                    Text(item.symbol)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoPrimary)

                    if let side = item.side {
                        DigestPill(text: side.uppercased(), color: side == "sell" ? .sevinoNegative : .sevinoPositive, scale: scale)
                    }
                }

                if let name = item.name {
                    Text(name)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoPrimary.opacity(0.56))
                        .lineLimit(1)
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2 * scale) {
                if let qty = item.qty {
                    Text(qty.asShareCount())
                        .font(.system(size: 14 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoPrimary)
                    Text(L10n.Digest.pendingShares)
                        .font(.system(size: 11 * scale))
                        .foregroundStyle(Color.sevinoPrimary.opacity(0.56))
                }

                if let notional = item.notional {
                    Text(notional.asCurrency())
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoPrimary.opacity(0.78))
                }
            }
        }
        .padding(.vertical, 9 * scale)
    }
}

#Preview {
    PendingOrdersCardView(
        card: PendingOrderActivityDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["MSFT", "VOO"],
            cardContext: [:],
            filled: [
                OrderActivityItemDTO(symbol: "MSFT", name: "Microsoft", side: "buy", qty: 1.5, notional: nil)
            ],
            recurringExecuted: [
                OrderActivityItemDTO(symbol: "VOO", name: "Vanguard S&P 500 ETF", side: "buy", qty: nil, notional: 25)
            ],
            recurringSkipped: []
        ),
        scale: 1
    )
    .padding()
}
