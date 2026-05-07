import Foundation

/// Protocol for fetching holdings data — enables mocking in previews and tests.
protocol HoldingsServiceProtocol {
    func fetchHoldings() async throws -> [Holding]
}

/// Hits `GET /v1/portfolio/holdings`, decodes the `HoldingsDTO`, and runs
/// `mapHoldings` to produce the pre-formatted `[Holding]` the UI consumes.
final class APIHoldingsService: HoldingsServiceProtocol {
    static let shared = APIHoldingsService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func fetchHoldings() async throws -> [Holding] {
        let dto: HoldingsDTO = try await api.get("/v1/portfolio/holdings")
        return mapHoldings(dto)
    }
}

/// Convert the wire-shape `HoldingsDTO` into the UI-shape `[Holding]`.
///
/// Decimal formatting happens here, at the service boundary, so the rest of
/// the app stays in the pre-formatted-string world that `HoldingRow`
/// already expects. The synthetic CASH row is always at index 0 — pinning
/// happens here, not in the view or view-model.
func mapHoldings(_ dto: HoldingsDTO) -> [Holding] {
    let cashRow = Holding(
        ticker: "CASH",
        isCash: true,
        shares: nil,
        value: dto.cash.asCurrency(),
        gainLossText: nil,
        isPositive: nil,
        daysGain: nil,
        daysGainPercent: nil,
        totalGain: nil,
        totalGainPercent: nil,
        averageCost: nil
    )

    let positionRows = dto.positions.map { p in
        Holding(
            ticker: p.symbol,
            isCash: false,
            shares: p.qty.asShareCount(),
            value: p.marketValue.asCurrency(),
            gainLossText: "\(p.unrealizedPl.asSignedCurrency()) (\(p.unrealizedPlpc.asSignedPercent()))",
            isPositive: p.unrealizedPl >= 0,
            daysGain: p.changeToday.asSignedCurrency(),
            daysGainPercent: p.changeTodayPercent.asSignedPercent(),
            totalGain: p.unrealizedPl.asSignedCurrency(),
            totalGainPercent: p.unrealizedPlpc.asSignedPercent(),
            averageCost: p.avgEntryPrice.asCurrency()
        )
    }

    return [cashRow] + positionRows
}
