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
/// Pure passthrough of Decimals — no formatting. The view formats at
/// render time using `NumberFormatting`, which keeps sort/filter logic
/// (PR #4) trivial: the VM compares `Decimal`s directly, never strings.
/// The synthetic CASH row is always at index 0.
func mapHoldings(_ dto: HoldingsDTO) -> [Holding] {
    let cashRow = Holding(
        ticker: "CASH",
        isCash: true,
        qty: nil,
        marketValue: dto.cash,
        unrealizedPl: nil,
        unrealizedPlpc: nil,
        changeToday: nil,
        changeTodayPercent: nil,
        avgEntryPrice: nil,
        buyingPower: dto.buyingPower
    )

    let positionRows = dto.positions.map { p in
        Holding(
            ticker: p.symbol,
            isCash: false,
            qty: p.qty,
            marketValue: p.marketValue,
            unrealizedPl: p.unrealizedPl,
            unrealizedPlpc: p.unrealizedPlpc,
            changeToday: p.changeToday,
            changeTodayPercent: p.changeTodayPercent,
            avgEntryPrice: p.avgEntryPrice,
            buyingPower: nil
        )
    }

    return [cashRow] + positionRows
}
