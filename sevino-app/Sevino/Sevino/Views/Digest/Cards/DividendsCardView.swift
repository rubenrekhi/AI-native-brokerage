import SwiftUI

struct DividendsCardView: View {
    let card: DividendsDigestCard
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 20 * scale) {
            VStack(alignment: .leading, spacing: 6 * scale) {
                Text(card.periodLabel)
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.62))

                Text(card.totalAmount.asCurrency())
                    .font(.dmSerif(size: 54 * scale))
                    .foregroundStyle(Color.sevinoPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }

            VStack(spacing: 0) {
                ForEach(Array(card.payments.enumerated()), id: \.element.id) { index, payment in
                    dividendRow(payment)
                    if index < card.payments.count - 1 {
                        Divider().background(Color.sevinoPrimary.opacity(0.12))
                    }
                }
            }

            Spacer(minLength: 0)
        }
    }

    private func dividendRow(_ payment: DividendPaymentDTO) -> some View {
        HStack(spacing: 12 * scale) {
            StockLogoView(ticker: payment.symbol, size: 28 * scale)

            VStack(alignment: .leading, spacing: 2 * scale) {
                Text(payment.symbol)
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoPrimary)

                Text(DigestCardFormatting.monthDay(payment.paidAt))
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.58))
            }

            Spacer()

            Text(payment.amount.asCurrency())
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoPrimary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .padding(.vertical, 10 * scale)
    }
}

#Preview {
    DividendsCardView(
        card: DividendsDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["AAPL", "MSFT"],
            cardContext: [:],
            payments: [
                DividendPaymentDTO(symbol: "AAPL", amount: 12.34, paidAt: Date(timeIntervalSince1970: 1_779_635_600)),
                DividendPaymentDTO(symbol: "MSFT", amount: 8.90, paidAt: Date(timeIntervalSince1970: 1_780_067_600))
            ],
            totalAmount: 21.24,
            periodLabel: "May dividends"
        ),
        scale: 1
    )
    .padding()
}
