import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

struct DigestStackView: View {
    let scale: CGFloat
    @Bindable var viewModel: DigestViewModel
    let onRouteToChat: () -> Void
    let onSubmitChat: (String, ChatDigestCard) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var dragOffset: CGFloat = 0

    private var cardSpacing: CGFloat { 16 * scale }

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()

            VStack(spacing: 0) {
                DigestHeaderView(
                    scale: scale,
                    closeAction: { Task { await closeToPeek() } }
                )

                GeometryReader { proxy in
                    let cardWidth = max(proxy.size.width - 48 * scale, 1)
                    HStack(spacing: cardSpacing) {
                        ForEach(viewModel.cards) { card in
                            DigestCardShell(card: card, scale: scale)
                                .frame(width: cardWidth, height: proxy.size.height)
                        }
                    }
                    .offset(x: stackOffset(cardWidth: cardWidth))
                    .animation(.spring(duration: 0.32, bounce: 0.16), value: viewModel.currentCardIndex)
                    .animation(.spring(duration: 0.25, bounce: 0.12), value: dragOffset)
                    .gesture(dragGesture(cardWidth: cardWidth))
                }
                .padding(.vertical, 20 * scale)

                DigestPageIndicator(
                    cards: viewModel.cards,
                    currentCardIndex: viewModel.currentCardIndex,
                    scale: scale
                )
                .padding(.bottom, 96 * scale)
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            DigestChatInputBar(
                scale: scale,
                viewModel: viewModel,
                onSubmit: { Task { await submitChat() } }
            )
            .padding(.horizontal, 16 * scale)
            .padding(.bottom, 10 * scale)
        }
        .simultaneousGesture(TapGesture().onEnded { dismissKeyboard() })
    }

    private func stackOffset(cardWidth: CGFloat) -> CGFloat {
        let step = cardWidth + cardSpacing
        return -CGFloat(viewModel.currentCardIndex) * step + dragOffset + 24 * scale
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
        dismiss()
    }

    private func closeToChat() async {
        await viewModel.dismissToPeek()
        dismiss()
        onRouteToChat()
    }

    private func submitChat() async {
        let text = viewModel.chatText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let card = viewModel.currentChatDigestCard() else { return }
        viewModel.clearChatText()
        await viewModel.dismissToPeek()
        dismiss()
        onSubmitChat(text, card)
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
    let scale: CGFloat
    let closeAction: () -> Void

    var body: some View {
        HStack {
            Text(L10n.Digest.title)
                .font(.dmSerif(size: 28 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .accessibilityIdentifier("digest.title")

            Spacer()

            Button(action: closeAction) {
                Image(systemName: "xmark")
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 40 * scale, height: 40 * scale)
                    .background(Color.sevinoSecondary.opacity(0.1), in: .circle)
            }
            .buttonStyle(.plain)
            .contentShape(.circle)
            .frame(minWidth: 44 * scale, minHeight: 44 * scale)
            .accessibilityLabel(L10n.Digest.dismissAccessibility)
            .accessibilityIdentifier("digest.close")
        }
        .padding(.horizontal, 24 * scale)
        .padding(.top, 20 * scale)
    }
}

private struct DigestPageIndicator: View {
    let cards: [DigestCard]
    let currentCardIndex: Int
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 7 * scale) {
            ForEach(Array(cards.enumerated()), id: \.element.id) { index, _ in
                Circle()
                    .fill(index == currentCardIndex ? Color.sevinoSecondary : Color.sevinoSecondary.opacity(0.28))
                    .frame(width: 7 * scale, height: 7 * scale)
            }
        }
        .accessibilityLabel(L10n.Digest.progressAccessibility(currentCardIndex + 1, cards.count))
        .accessibilityIdentifier("digest.progress")
    }
}

private struct DigestCardShell: View {
    let card: DigestCard
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 18 * scale) {
            Text(card.kind.replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.system(size: 15 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary.opacity(0.68))

            DigestCardBody(card: card, scale: scale)

            Spacer(minLength: 0)
        }
        .padding(24 * scale)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.sevinoSecondary, in: .rect(cornerRadius: 8 * scale))
        .foregroundStyle(Color.sevinoPrimary)
    }
}

private struct DigestCardBody: View {
    let card: DigestCard
    let scale: CGFloat

    var body: some View {
        switch card {
        case .dividends(let card):
            DividendsCardView(card: card, scale: scale)
        case .pendingOrderActivity(let card):
            PendingOrdersCardView(card: card, scale: scale)
        case .bigMove(let card):
            BigMoveCardView(card: card, scale: scale)
        case .watchlistMove(let card):
            WatchlistMoveCardView(card: card, scale: scale)
        case .marketContext(let card):
            MarketContextCardView(card: card, scale: scale)
        case .radarRefresh(let card):
            RadarRefreshCardView(card: card, scale: scale)
        case .earningsResult(let card):
            EarningsResultCardView(card: card, scale: scale)
        case .upcomingEarnings(let card):
            UpcomingEarningsCardView(card: card, scale: scale)
        case .news(let card):
            NewsCardView(card: card, scale: scale)
        }
    }
}

#Preview {
    let viewModel = DigestViewModel(client: PlaceholderDigestAPIClient())
    return DigestStackView(
        scale: 1,
        viewModel: viewModel,
        onRouteToChat: {},
        onSubmitChat: { _, _ in }
    )
        .task { await viewModel.refreshForForeground() }
}
