import Foundation

/// Protocol for the brokerage trading endpoints — orders and positions. Used
/// by the trade-history screen and any future trading UI.
protocol TradingServiceProtocol: Sendable {
    func listOrders(
        status: String?,
        side: String?,
        symbols: String?,
        after: Date?,
        until: Date?,
        limit: Int
    ) async throws -> [OrderResponse]

    func listPositions() async throws -> [PositionResponse]
}

extension TradingServiceProtocol {
    func listOrders() async throws -> [OrderResponse] {
        try await listOrders(
            status: nil,
            side: nil,
            symbols: nil,
            after: nil,
            until: nil,
            limit: 100
        )
    }
}

/// Calls `GET /v1/brokerage/orders` and `GET /v1/brokerage/positions`.
final class TradingService: TradingServiceProtocol {
    static let shared = TradingService()

    private let api: any APIClientProtocol

    init(api: any APIClientProtocol = APIClient.shared) {
        self.api = api
    }

    func listOrders(
        status: String? = nil,
        side: String? = nil,
        symbols: String? = nil,
        after: Date? = nil,
        until: Date? = nil,
        limit: Int = 100
    ) async throws -> [OrderResponse] {
        var components = URLComponents()
        components.path = "/v1/brokerage/orders"

        var items: [URLQueryItem] = [URLQueryItem(name: "limit", value: String(limit))]
        if let status { items.append(URLQueryItem(name: "status", value: status)) }
        if let side { items.append(URLQueryItem(name: "side", value: side)) }
        if let symbols, !symbols.isEmpty {
            items.append(URLQueryItem(name: "symbols", value: symbols))
        }
        if let after {
            items.append(URLQueryItem(name: "after", value: Self.iso8601.string(from: after)))
        }
        if let until {
            items.append(URLQueryItem(name: "until", value: Self.iso8601.string(from: until)))
        }
        components.queryItems = items

        guard let path = components.string else { throw URLError(.badURL) }

        let response: OrderListResponse = try await api.get(path)
        return response.orders
    }

    func listPositions() async throws -> [PositionResponse] {
        let response: PositionListResponse = try await api.get("/v1/brokerage/positions")
        return response.positions
    }

    private static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()
}
