import SwiftUI

enum TypewriterAnimation {
    static let defaultSpeed: Duration = .milliseconds(21)

    static func typeOut(
        _ text: String,
        speed: Duration = defaultSpeed,
        reduceMotion: Bool = false,
        update: (String) -> Void
    ) async {
        guard !text.isEmpty else { return }
        if reduceMotion {
            update(text)
            return
        }
        var buffer = ""
        buffer.reserveCapacity(text.count)
        for char in text {
            guard !Task.isCancelled else { return }
            buffer.append(char)
            update(buffer)
            try? await Task.sleep(for: speed)
        }
    }
}

/// Per-tick typewriter math for streaming chat text. Snaps when `target`
/// diverges from `current` (e.g. a `block_data` patch rewrote the text), since
/// no monotonic catch-up is possible from a non-prefix.
enum TypewriterStreamingBuffer {
    static func advance(from current: String, toward target: String) -> String {
        guard target.hasPrefix(current), current.count < target.count else {
            return target
        }
        let remaining = target.count - current.count
        let chunk = chunkSize(forRemaining: remaining)
        let nextCount = min(current.count + chunk, target.count)
        let endIndex = target.index(target.startIndex, offsetBy: nextCount)
        return String(target[..<endIndex])
    }

    /// Characters to reveal on a single tick when `remaining` chars separate the
    /// displayed prefix from the target. Tuned for a 21 ms tick:
    /// - Near the target: 1 char/tick ≈ 47 cps — matches onboarding cadence.
    /// - Catching up (>47 chars behind): ≥2 chars/tick ≈ ≥95 cps — clears the
    ///   ≥60 cps floor the acceptance criterion asks for.
    /// - Big backlog (>600 chars behind): linear in `remaining` so an 800-char
    ///   delta converges in ~1 s instead of the 17 s a flat 47 cps would take.
    static func chunkSize(forRemaining remaining: Int) -> Int {
        switch remaining {
        case ..<1: return 0
        case ...47: return 1
        case ...120: return 2
        case ...600: return 5
        default: return max(8, remaining / 50)
        }
    }
}
