import Foundation

/// Protocol for fetching holdings data — enables mocking in previews and tests.
protocol HoldingsServiceProtocol {
    func fetchHoldings() async throws -> [Holding]
}

/// Real backend impl. Hits `GET /v1/portfolio/holdings` and prepends a synthetic
/// CASH row so the view can render a single ordered list.
final class APIHoldingsService: HoldingsServiceProtocol {
    static let shared = APIHoldingsService()
    private let client: any APIClientProtocol

    init(client: any APIClientProtocol = APIClient.shared) { self.client = client }

    func fetchHoldings() async throws -> [Holding] {
        let dto: HoldingsDTO = try await client.get("/v1/portfolio/holdings")
        var result: [Holding] = [Self.cashRow(dto.cash)]
        result.append(contentsOf: dto.positions.map(Self.positionToHolding))
        return result
    }

    private static func cashRow(_ cash: Decimal) -> Holding {
        Holding(
            ticker: "CASH", isCash: true, name: "Cash",
            qty: nil, marketValue: cash,
            avgEntryPrice: nil, unrealizedPl: nil, unrealizedPlpc: nil
        )
    }

    private static func positionToHolding(_ p: PositionDTO) -> Holding {
        Holding(
            ticker: p.symbol, isCash: false, name: p.name,
            qty: p.qty, marketValue: p.marketValue,
            avgEntryPrice: p.avgEntryPrice,
            unrealizedPl: p.unrealizedPl,
            unrealizedPlpc: p.unrealizedPlpc
        )
    }
}

/// Placeholder implementation that returns canned holdings. This is the default
/// service used by `HoldingsViewModel` until the backend endpoint exists — it is
/// not a test double.
final class PlaceholderHoldingsService: HoldingsServiceProtocol {
    static let shared = PlaceholderHoldingsService()

    func fetchHoldings() async throws -> [Holding] {
        [
            Holding(
                ticker: "CASH", isCash: true, name: "Cash",
                qty: nil, marketValue: Decimal(string: "40291.92")!,
                avgEntryPrice: nil, unrealizedPl: nil, unrealizedPlpc: nil
            ),
            Holding(
                ticker: "TSLA", isCash: false, name: "Tesla, Inc.",
                qty: Decimal(57), marketValue: Decimal(string: "21748.18")!,
                avgEntryPrice: Decimal(string: "248.91")!,
                unrealizedPl: Decimal(string: "7418.90")!,
                unrealizedPlpc: Decimal(string: "0.5174")!
            ),
            Holding(
                ticker: "AMD", isCash: false, name: "Advanced Micro Devices",
                qty: Decimal(37), marketValue: Decimal(string: "11465.19")!,
                avgEntryPrice: Decimal(string: "338.23")!,
                unrealizedPl: Decimal(string: "-1049.32")!,
                unrealizedPlpc: Decimal(string: "-0.0838")!
            ),
        ]
    }
}
