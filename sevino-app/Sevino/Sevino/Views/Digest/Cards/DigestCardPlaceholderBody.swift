import SwiftUI

struct DigestCardPlaceholderBody: View {
    let card: DigestCard
    let scale: CGFloat

    var body: some View {
        switch card {
        case .dividends:
            DividendsDigestPlaceholder(kind: card.kind, scale: scale)
        case .pendingOrderActivity:
            PendingOrderActivityDigestPlaceholder(kind: card.kind, scale: scale)
        case .bigMove:
            BigMoveDigestPlaceholder(kind: card.kind, scale: scale)
        case .watchlistMove:
            WatchlistMoveDigestPlaceholder(kind: card.kind, scale: scale)
        case .marketContext:
            MarketContextDigestPlaceholder(kind: card.kind, scale: scale)
        case .radarRefresh:
            RadarRefreshDigestPlaceholder(kind: card.kind, scale: scale)
        case .earningsResult:
            EarningsResultDigestPlaceholder(kind: card.kind, scale: scale)
        case .upcomingEarnings:
            UpcomingEarningsDigestPlaceholder(kind: card.kind, scale: scale)
        case .news:
            NewsDigestPlaceholder(kind: card.kind, scale: scale)
        }
    }
}

private struct DividendsDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct PendingOrderActivityDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct BigMoveDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct WatchlistMoveDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct MarketContextDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct RadarRefreshDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct EarningsResultDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct UpcomingEarningsDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct NewsDigestPlaceholder: View {
    let kind: String
    let scale: CGFloat
    var body: some View { PlaceholderDigestCardBody(kind: kind, scale: scale) }
}

private struct PlaceholderDigestCardBody: View {
    let kind: String
    let scale: CGFloat

    var body: some View {
        Text(kind)
            .font(.system(size: 34 * scale, weight: .semibold))
            .foregroundStyle(Color.sevinoPrimary)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            .minimumScaleFactor(0.6)
    }
}
