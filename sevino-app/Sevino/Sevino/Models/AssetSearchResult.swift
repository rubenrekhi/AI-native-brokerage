import Foundation

/// A single asset returned by `GET /v1/assets/search`.
/// `logoUrl` is optional because the backend may not have a logo for every symbol.
struct AssetSearchResult: Codable, Identifiable, Equatable, Sendable {
    let symbol: String
    let name: String
    let logoUrl: String?

    var id: String { symbol }
}
