import Foundation

/// Gates each text block's typewriter on the prior one. Text blocks N+1
/// stays hidden until block N has caught up to its final text. Non-text
/// blocks (status pills, stock cards) are not affected — they render
/// immediately on arrival.
@Observable
@MainActor
final class MessageTypewriterSequencer {
    private(set) var unlockedThroughOrdinal: Int = 0

    func isUnlocked(ordinal: Int) -> Bool {
        ordinal <= unlockedThroughOrdinal
    }

    func markCompleted(ordinal: Int) {
        if ordinal >= unlockedThroughOrdinal {
            unlockedThroughOrdinal = ordinal + 1
        }
    }
}
