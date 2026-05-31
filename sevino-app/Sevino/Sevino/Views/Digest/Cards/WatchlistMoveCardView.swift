import SwiftUI

struct WatchlistMoveCardView: View {
    let card: WatchlistMoveDigestCard
    let scale: CGFloat

    var body: some View {
        PriceMoveCardBody(
            symbol: card.symbol,
            name: card.name,
            prevClose: card.prevClose,
            current: card.current,
            changeAbs: card.changeAbs,
            changePct: card.changePct,
            reason: card.reason,
            badgeText: L10n.Digest.watchlistBadge,
            scale: scale
        )
    }
}

#Preview {
    WatchlistMoveCardView(
        card: WatchlistMoveDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["TSLA"],
            cardContext: [:],
            symbol: "TSLA",
            name: "Tesla",
            prevClose: 200,
            current: 190,
            changeAbs: -10,
            changePct: -0.05,
            reason: "The move followed delivery estimate revisions."
        ),
        scale: 1
    )
    .padding()
}
