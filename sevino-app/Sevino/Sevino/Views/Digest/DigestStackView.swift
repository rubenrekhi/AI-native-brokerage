import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

struct DigestStackView: View {
    let scale: CGFloat
    @Bindable var viewModel: DigestViewModel
    let onRouteToChat: () -> Void

    @State private var dragOffset: CGFloat = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            Spacer(minLength: 0)

            DigestHeaderView(
                snapshotDate: viewModel.snapshot?.generatedAt ?? .now,
                cards: viewModel.cards,
                currentCardIndex: viewModel.currentCardIndex,
                scale: scale,
                closeAction: { Task { await closeToPeek() } }
            )

            GeometryReader { proxy in
                if let card = viewModel.currentCard {
                    DigestStoryCard(card: card, scale: scale)
                        .frame(
                            width: min(proxy.size.width, 360 * scale),
                            alignment: .top
                        )
                        .frame(maxHeight: min(proxy.size.height, 460 * scale), alignment: .top)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .offset(x: dragOffset)
                        .animation(.spring(duration: 0.32, bounce: 0.16), value: viewModel.currentCardIndex)
                        .animation(.spring(duration: 0.25, bounce: 0.12), value: dragOffset)
                        .gesture(dragGesture(cardWidth: proxy.size.width))
                }
            }
            .frame(maxHeight: 460 * scale)
        }
        .frame(maxWidth: 390 * scale, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.horizontal, 20 * scale)
        .simultaneousGesture(TapGesture().onEnded { dismissKeyboard() })
    }

    private func dragGesture(cardWidth: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 12 * scale)
            .onChanged { value in
                dragOffset = value.translation.width
            }
            .onEnded { value in
                let threshold = min(cardWidth * 0.22, 96 * scale)
                let translation = value.predictedEndTranslation.width
                dragOffset = 0

                if translation < -threshold {
                    if !viewModel.showNextCard() {
                        Task { await closeToChat() }
                    }
                } else if translation > threshold {
                    viewModel.showPreviousCard()
                }
            }
    }

    private func closeToPeek() async {
        await viewModel.dismissToPeek()
    }

    private func closeToChat() async {
        await viewModel.dismissToPeek()
        onRouteToChat()
    }

    private func dismissKeyboard() {
        #if canImport(UIKit)
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
        #endif
    }
}

private struct DigestHeaderView: View {
    let snapshotDate: Date
    let cards: [DigestCard]
    let currentCardIndex: Int
    let scale: CGFloat
    let closeAction: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12 * scale) {
            VStack(alignment: .leading, spacing: 4 * scale) {
                Text(L10n.Digest.dailyDigestEyebrow)
                    .font(.system(size: 12 * scale, weight: .bold))
                    .kerning(3 * scale)
                    .foregroundStyle(Color.sevinoSecondary.opacity(0.72))
                    .accessibilityIdentifier("digest.title")

                Text(snapshotDate.formatted(.dateTime.weekday(.wide).month(.abbreviated).day()))
                    .font(.system(size: 17 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
            }

            Spacer()

            DigestPageIndicator(
                cards: cards,
                currentCardIndex: currentCardIndex,
                scale: scale
            )
            .padding(.top, 8 * scale)

            Button(action: closeAction) {
                Image(systemName: "xmark")
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 38 * scale, height: 38 * scale)
                    .background(Color.digestCloseButtonBackground, in: .circle)
            }
            .buttonStyle(.plain)
            .contentShape(.circle)
            .frame(minWidth: 44 * scale, minHeight: 44 * scale)
            .accessibilityLabel(L10n.Digest.dismissAccessibility)
            .accessibilityIdentifier("digest.close")
        }
    }
}

private struct DigestPageIndicator: View {
    let cards: [DigestCard]
    let currentCardIndex: Int
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 4 * scale) {
            ForEach(Array(cards.enumerated()), id: \.element.id) { index, _ in
                Capsule()
                    .fill(index == currentCardIndex ? Color.sevinoSecondary : Color.sevinoSecondary.opacity(0.16))
                    .frame(width: index == currentCardIndex ? 20 * scale : 5 * scale, height: 5 * scale)
            }
        }
        .accessibilityLabel(L10n.Digest.progressAccessibility(currentCardIndex + 1, cards.count))
        .accessibilityIdentifier("digest.progress")
    }
}

private struct DigestStoryCard: View {
    let card: DigestCard
    let scale: CGFloat

    var body: some View {
        let story = DigestStory(card: card)

        VStack(alignment: .leading, spacing: 18 * scale) {
            HStack(spacing: 8 * scale) {
                Image(systemName: story.icon)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary.opacity(0.72))

                Text(story.eyebrow)
                    .font(.system(size: 12 * scale, weight: .bold))
                    .kerning(2 * scale)
                    .foregroundStyle(Color.sevinoSecondary.opacity(0.72))
                    .lineLimit(1)
            }

            Text(story.title)
                .font(.system(size: 30 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
                .lineLimit(3)
                .minimumScaleFactor(0.76)
                .fixedSize(horizontal: false, vertical: true)

            VStack(alignment: .leading, spacing: 8 * scale) {
                if let symbol = story.symbol {
                    Text(symbol)
                        .font(.system(size: 12 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary.opacity(0.68))
                        .padding(.horizontal, 10 * scale)
                        .padding(.vertical, 5 * scale)
                        .background(Color.sevinoSecondary.opacity(0.08), in: .capsule)
                }

                HStack(alignment: .firstTextBaseline, spacing: 10 * scale) {
                    Text(story.metric)
                        .font(.system(size: 38 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)

                    if let accent = story.accent {
                        Text(accent)
                            .font(.system(size: 16 * scale, weight: .bold))
                            .foregroundStyle(story.accentColor)
                            .lineLimit(1)
                            .minimumScaleFactor(0.72)
                    }
                }
            }

            Text(story.summary)
                .font(.system(size: 16 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary.opacity(0.70))
                .lineSpacing(3 * scale)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)
        }
        .padding(28 * scale)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color.digestCardSurface, in: .rect(cornerRadius: 30 * scale))
        .overlay {
            RoundedRectangle(cornerRadius: 30 * scale)
                .stroke(Color.digestCardBorder, lineWidth: 1)
        }
        .shadow(color: Color.sevinoShadow.opacity(0.12), radius: 28 * scale, x: 0, y: 18 * scale)
    }
}

private struct DigestStory {
    let eyebrow: String
    let icon: String
    let title: String
    let symbol: String?
    let metric: String
    let accent: String?
    let accentColor: Color
    let summary: String

    init(card: DigestCard) {
        switch card {
        case .dividends(let card):
            eyebrow = L10n.Digest.storyDividendsEyebrow
            icon = "banknote"
            title = L10n.Digest.storyDividendsTitle(card.periodLabel)
            symbol = card.relatedSymbols.first
            metric = card.totalAmount.asCurrency()
            accent = L10n.Digest.storyPaymentsCount(card.payments.count)
            accentColor = .sevinoPositive
            summary = L10n.Digest.storyDividendsSummary(Self.symbolList(card.relatedSymbols))
        case .pendingOrderActivity(let card):
            let count = card.filled.count + card.recurringExecuted.count + card.recurringSkipped.count
            eyebrow = L10n.Digest.storyOrdersEyebrow
            icon = "arrow.left.arrow.right"
            title = L10n.Digest.storyOrdersTitle
            symbol = card.relatedSymbols.first
            metric = "\(count)"
            accent = L10n.Digest.storyOrdersUnit(count)
            accentColor = .sevinoInfo
            summary = L10n.Digest.storyOrdersSummary(Self.symbolList(card.relatedSymbols))
        case .bigMove(let card):
            eyebrow = L10n.Digest.storyBigMoveEyebrow(card.symbol)
            icon = "chart.line.uptrend.xyaxis"
            title = L10n.Digest.storyMoveTitle(card.name, card.changePct.asSignedPercent())
            symbol = card.symbol
            metric = card.current.asCurrency()
            accent = "\(card.changeAbs.asSignedCurrency()) (\(card.changePct.asSignedPercent()))"
            accentColor = card.changePct.digestSignedColor
            summary = card.reason ?? L10n.Digest.storyMoveSummaryFallback(card.symbol, card.prevClose.asCurrency(), card.current.asCurrency())
        case .watchlistMove(let card):
            eyebrow = L10n.Digest.storyWatchlistEyebrow(card.symbol)
            icon = "eye"
            title = L10n.Digest.storyMoveTitle(card.name, card.changePct.asSignedPercent())
            symbol = card.symbol
            metric = card.current.asCurrency()
            accent = "\(card.changeAbs.asSignedCurrency()) (\(card.changePct.asSignedPercent()))"
            accentColor = card.changePct.digestSignedColor
            summary = card.reason ?? L10n.Digest.storyMoveSummaryFallback(card.symbol, card.prevClose.asCurrency(), card.current.asCurrency())
        case .marketContext(let card):
            eyebrow = L10n.Digest.storyMarketEyebrow
            icon = "globe.americas"
            title = Self.marketTitle(card.direction)
            symbol = "SPY"
            metric = card.sp500ChangePct.asSignedPercent()
            accent = L10n.Digest.storyNasdaqAccent(card.nasdaqChangePct.asSignedPercent())
            accentColor = card.sp500ChangePct.digestSignedColor
            summary = card.summary
        case .radarRefresh(let card):
            eyebrow = L10n.Digest.storyRadarEyebrow
            icon = "sparkles"
            title = L10n.Digest.storyRadarTitle
            symbol = card.relatedSymbols.first
            metric = "\(card.newCount)"
            accent = L10n.Digest.storyRadarAccent
            accentColor = .sevinoPositive
            summary = L10n.Digest.storyRadarSummary(Self.symbolList(card.relatedSymbols))
        case .earningsResult(let card):
            eyebrow = L10n.Digest.storyEarningsEyebrow(card.symbol)
            icon = "doc.text.magnifyingglass"
            title = L10n.Digest.storyEarningsTitle(card.name)
            symbol = card.symbol
            metric = card.grade
            accent = card.stockReactionPct.map { L10n.Digest.storyEarningsReaction($0.asSignedPercent()) }
            accentColor = card.stockReactionPct?.digestSignedColor ?? .sevinoInfo
            summary = card.beatMissHighlights.joined(separator: ". ")
        case .upcomingEarnings(let card):
            eyebrow = L10n.Digest.storyUpcomingEyebrow(card.symbol)
            icon = "calendar"
            title = L10n.Digest.storyUpcomingTitle(card.name, card.relativeLabel.lowercased())
            symbol = card.symbol
            metric = card.relativeLabel
            accent = nil
            accentColor = .sevinoInfo
            summary = L10n.Digest.storyUpcomingSummary(DigestCardFormatting.dateTime(card.reportsAt))
        case .news(let card):
            eyebrow = card.symbol.map { L10n.Digest.storyNewsEyebrowSymbol($0) } ?? L10n.Digest.storyNewsEyebrow
            icon = "newspaper"
            title = card.headline
            symbol = card.symbol
            metric = card.source
            accent = DigestCardFormatting.timeAgo(card.publishedAt)
            accentColor = .sevinoInfo
            summary = card.summary
        }
    }

    private static func symbolList(_ symbols: [String]) -> String {
        if symbols.isEmpty { return L10n.Digest.storySymbolsFallback }
        return symbols.prefix(4).joined(separator: ", ")
    }

    private static func marketTitle(_ direction: String) -> String {
        switch direction {
        case "up": return L10n.Digest.marketDirectionUp
        case "down": return L10n.Digest.marketDirectionDown
        default: return L10n.Digest.marketDirectionMixed
        }
    }
}

#Preview {
    let viewModel = DigestViewModel(client: PlaceholderDigestAPIClient())
    return DigestStackView(
        scale: 1,
        viewModel: viewModel,
        onRouteToChat: {}
    )
        .task { await viewModel.refreshForForeground() }
}
