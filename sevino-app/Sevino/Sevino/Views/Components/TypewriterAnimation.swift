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
