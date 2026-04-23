import Foundation

/// A committed ticker mention in the chat input text. The `range` points at the
/// `$SYMBOL` substring inside `TickerMentionViewModel.text`.
struct TickerToken: Identifiable, Equatable, Hashable, Sendable {
    let id: UUID
    let symbol: String
    var range: Range<Int>

    init(id: UUID = UUID(), symbol: String, range: Range<Int>) {
        self.id = id
        self.symbol = symbol
        self.range = range
    }
}

/// Drives the $-triggered ticker mention flow in the chat input.
///
/// Responsibilities:
///   1. Detect the trailing `$QUERY` pattern — `$` followed by letter characters — and treat it
///      as the active mention. `$` followed by a digit (e.g. `$20`) is treated as a dollar amount
///      and ignored.
///   2. Debounce search requests by 300ms and cancel in-flight requests on each keystroke.
///   3. Track committed tokens in the text and keep their ranges anchored when the user edits
///      surrounding characters.
///   4. Convert the active mention to a token on selection from the popup, or on space completion
///      when the typed text is a valid 1-5 letter uppercase ticker.
@Observable
final class TickerMentionViewModel {
    /// The chat input text. The view must route edits through `updateText(_:)` so the
    /// view model can reconcile tokens and detect space completion.
    private(set) var text: String = ""

    /// Assets returned for the current active query. Empty when the popup is hidden.
    private(set) var results: [AssetSearchResult] = []

    /// All committed ticker tokens in the text, in left-to-right order.
    private(set) var tokens: [TickerToken] = []

    /// The letters following the active `$` trigger, if any. `nil` when no mention is being typed.
    private(set) var activeQuery: String?

    /// True when there is an active query AND results are available to display.
    var isShowingPopup: Bool {
        activeQuery != nil && !results.isEmpty
    }

    private var activeRange: Range<Int>?
    private var searchTask: Task<Void, Never>?
    private let service: any AssetSearchServiceProtocol
    private let debounceInterval: Duration

    init(
        service: any AssetSearchServiceProtocol = AssetSearchService.shared,
        debounceInterval: Duration = .milliseconds(300)
    ) {
        self.service = service
        self.debounceInterval = debounceInterval
    }

    // MARK: - Public API

    /// Called by the view whenever the chat input text changes.
    func updateText(_ newText: String) {
        let previousText = text
        let previousQuery = activeQuery
        let previousRange = activeRange
        text = newText
        reconcileTokens()
        refreshActiveMention()
        commitOnSpaceIfNeeded(previousText: previousText, previousQuery: previousQuery, previousRange: previousRange)
        scheduleSearch()
    }

    /// Replace the active `$QUERY` with `$SYMBOL` and dismiss the popup.
    func selectResult(_ result: AssetSearchResult) {
        guard let range = activeRange else { return }
        let replacement = "$\(result.symbol)"
        replaceCharacters(in: range, with: replacement)
        let newRange = range.lowerBound..<(range.lowerBound + replacement.count)
        shiftTokens(after: range.upperBound, by: replacement.count - range.count)
        tokens.append(TickerToken(symbol: result.symbol, range: newRange))
        sortTokens()
        dismiss()
    }

    /// Atomically remove a committed token from both `tokens` and the underlying text.
    func removeToken(id: UUID) {
        guard let index = tokens.firstIndex(where: { $0.id == id }) else { return }
        let token = tokens[index]
        let removedLength = token.range.count
        replaceCharacters(in: token.range, with: "")
        tokens.remove(at: index)
        shiftTokens(after: token.range.upperBound, by: -removedLength)
        refreshActiveMention()
        scheduleSearch()
    }

    /// Cancel any in-flight search and hide the popup — invoked when the parent view
    /// detects a tap outside the suggestion popup.
    func dismiss() {
        searchTask?.cancel()
        searchTask = nil
        results = []
        activeQuery = nil
        activeRange = nil
    }

    // MARK: - Mention detection

    /// Scans backwards from the end of `text` for a `$QUERY` pattern — `$` followed by 1+ letters —
    /// that is not part of a committed token. Sets `activeQuery` and `activeRange` accordingly.
    private func refreshActiveMention() {
        var letterCount = 0
        var index = text.endIndex
        while index > text.startIndex {
            let prev = text.index(before: index)
            let char = text[prev]
            if char == "$" {
                let lowerInt = text.distance(from: text.startIndex, to: prev)
                if letterCount == 0 || isWithinToken(offset: lowerInt) {
                    activeQuery = nil
                    activeRange = nil
                    return
                }
                let upperInt = lowerInt + 1 + letterCount
                let queryStart = text.index(after: prev)
                activeQuery = String(text[queryStart..<text.endIndex])
                activeRange = lowerInt..<upperInt
                return
            }
            if char.isLetter {
                letterCount += 1
                index = prev
                continue
            }
            // Any non-letter, non-`$` character (digit, space, punctuation) terminates the scan —
            // the text does not end in an active mention.
            activeQuery = nil
            activeRange = nil
            return
        }
        activeQuery = nil
        activeRange = nil
    }

    private func isWithinToken(offset: Int) -> Bool {
        tokens.contains { $0.range.contains(offset) }
    }

    // MARK: - Space completion

    /// If the only change between `previousText` and `text` was a single space appended directly
    /// after a valid active mention, commit that mention as a token.
    private func commitOnSpaceIfNeeded(previousText: String, previousQuery: String?, previousRange: Range<Int>?) {
        guard let previousQuery, let previousRange,
              isValidTicker(previousQuery),
              activeQuery == nil,
              text.count == previousText.count + 1
        else { return }
        let splitIdx = text.index(text.startIndex, offsetBy: previousRange.upperBound, limitedBy: text.endIndex)
        guard let splitIdx, splitIdx < text.endIndex, text[splitIdx] == " " else { return }
        let lowerIdx = text.index(text.startIndex, offsetBy: previousRange.lowerBound)
        guard text[lowerIdx..<splitIdx] == "$\(previousQuery)" else { return }
        tokens.append(TickerToken(symbol: previousQuery.uppercased(), range: previousRange))
        sortTokens()
    }

    private func isValidTicker(_ query: String) -> Bool {
        guard (1...5).contains(query.count) else { return false }
        return query.allSatisfy { ("A"..."Z").contains($0) }
    }

    // MARK: - Token reconciliation

    /// Re-anchors each existing token's `range` to the new `text`. Tokens whose `$SYMBOL`
    /// substring can no longer be located are dropped — this is how edits to a token's
    /// characters remove the token.
    private func reconcileTokens() {
        var remaining: [TickerToken] = []
        var cursor = text.startIndex
        for token in tokens.sorted(by: { $0.range.lowerBound < $1.range.lowerBound }) {
            let needle = "$\(token.symbol)"
            guard let found = text.range(of: needle, range: cursor..<text.endIndex) else { continue }
            let lower = text.distance(from: text.startIndex, to: found.lowerBound)
            let upper = text.distance(from: text.startIndex, to: found.upperBound)
            remaining.append(TickerToken(id: token.id, symbol: token.symbol, range: lower..<upper))
            cursor = found.upperBound
        }
        tokens = remaining
    }

    private func shiftTokens(after offset: Int, by delta: Int) {
        guard delta != 0 else { return }
        for index in tokens.indices where tokens[index].range.lowerBound >= offset {
            let lower = tokens[index].range.lowerBound + delta
            let upper = tokens[index].range.upperBound + delta
            tokens[index].range = lower..<upper
        }
    }

    private func sortTokens() {
        tokens.sort { $0.range.lowerBound < $1.range.lowerBound }
    }

    // MARK: - Search scheduling

    private func scheduleSearch() {
        searchTask?.cancel()
        guard let query = activeQuery, !query.isEmpty else {
            results = []
            searchTask = nil
            return
        }
        let delay = debounceInterval
        let service = service
        searchTask = Task { [weak self] in
            try? await Task.sleep(for: delay)
            if Task.isCancelled { return }
            let fetched: [AssetSearchResult]
            do {
                fetched = try await service.search(query: query)
            } catch {
                return
            }
            if Task.isCancelled { return }
            guard let self, self.activeQuery == query else { return }
            self.results = fetched
        }
    }

    // MARK: - Text editing

    private func replaceCharacters(in range: Range<Int>, with replacement: String) {
        let start = text.index(text.startIndex, offsetBy: range.lowerBound)
        let end = text.index(text.startIndex, offsetBy: range.upperBound)
        text.replaceSubrange(start..<end, with: replacement)
    }
}
