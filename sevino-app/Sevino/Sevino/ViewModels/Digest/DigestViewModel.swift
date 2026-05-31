import Foundation

@Observable
final class DigestViewModel {
    enum PresentationState: Equatable {
        case full
        case peek
        case hidden
    }

    private let client: any DigestAPIClientProtocol

    private(set) var snapshot: DigestSnapshotDTO?
    private(set) var presentationState: PresentationState = .hidden
    private(set) var isLoading = false
    private(set) var error: String?
    private(set) var currentCardIndex = 0
    var chatText = ""

    var cards: [DigestCard] {
        snapshot?.cards ?? []
    }

    var currentCard: DigestCard? {
        guard cards.indices.contains(currentCardIndex) else { return nil }
        return cards[currentCardIndex]
    }

    init(client: any DigestAPIClientProtocol = APIClient.shared) {
        self.client = client
    }

    func refreshForForeground() async {
        error = nil
        isLoading = true
        defer { isLoading = false }

        do {
            guard let response = try await client.getTodaysDigest(),
                  !response.snapshot.cards.isEmpty else {
                snapshot = nil
                currentCardIndex = 0
                presentationState = .hidden
                return
            }

            snapshot = response.snapshot
            currentCardIndex = min(currentCardIndex, max(response.snapshot.cards.count - 1, 0))
            presentationState = response.snapshot.dismissedAt == nil ? .full : .peek
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func reopenDigest() {
        guard !cards.isEmpty else { return }
        currentCardIndex = min(currentCardIndex, cards.count - 1)
        presentationState = .full
    }

    func showPreviousCard() {
        currentCardIndex = max(0, currentCardIndex - 1)
    }

    /// Returns false when the caller attempted to advance past the final card.
    @discardableResult
    func showNextCard() -> Bool {
        guard currentCardIndex < cards.count - 1 else { return false }
        currentCardIndex += 1
        return true
    }

    func dismissToPeek() async {
        guard !cards.isEmpty else {
            presentationState = .hidden
            currentCardIndex = 0
            return
        }

        presentationState = .peek
        currentCardIndex = 0
        do {
            try await client.dismissDigest()
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }

    func clearChatText() {
        chatText = ""
    }

    func currentChatDigestCard() -> ChatDigestCard? {
        guard let currentCard else { return nil }
        return try? ChatDigestCard(digestCard: currentCard)
    }
}
