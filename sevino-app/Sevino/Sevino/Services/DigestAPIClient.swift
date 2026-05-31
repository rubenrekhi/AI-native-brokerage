import Foundation

protocol DigestAPIClientProtocol: Sendable {
    func getTodaysDigest() async throws -> DigestTodayResponseDTO?
    func dismissDigest() async throws
}

extension APIClient: DigestAPIClientProtocol {}

struct PlaceholderDigestAPIClient: DigestAPIClientProtocol {
    func getTodaysDigest() async throws -> DigestTodayResponseDTO? {
        DigestTodayResponseDTO(
            snapshot: DigestSnapshotDTO(
                id: UUID(),
                nyLocalDate: "2026-05-31",
                cards: [
                    .marketContext(MarketContextDigestCard(
                        id: UUID(),
                        priority: 0,
                        relatedSymbols: [],
                        cardContext: [:],
                        direction: "mixed",
                        sp500ChangePct: 0.01,
                        nasdaqChangePct: -0.02,
                        summary: "Preview"
                    )),
                    .news(NewsDigestCard(
                        id: UUID(),
                        priority: 1,
                        relatedSymbols: ["AAPL"],
                        cardContext: [:],
                        symbol: "AAPL",
                        headline: "Preview headline",
                        source: "Preview",
                        url: "https://example.com",
                        publishedAt: Date(),
                        summary: "Preview"
                    )),
                ],
                generatedAt: Date(),
                dismissedAt: nil,
                createdAt: Date()
            ),
            peekVisible: false
        )
    }

    func dismissDigest() async throws {}
}
