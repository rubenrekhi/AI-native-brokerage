import SwiftUI

struct BigMoveCardView: View {
    let card: BigMoveDigestCard
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
            badgeText: nil,
            scale: scale
        )
    }
}

#Preview {
    BigMoveCardView(
        card: BigMoveDigestCard(
            id: UUID(),
            priority: 0,
            relatedSymbols: ["NVDA"],
            cardContext: [:],
            symbol: "NVDA",
            name: "NVIDIA",
            prevClose: 100,
            current: 108,
            changeAbs: 8,
            changePct: 0.08,
            reason: "Shares moved after updated chip export guidance."
        ),
        scale: 1
    )
    .padding()
}
