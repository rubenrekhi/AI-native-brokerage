#if DEBUG
import Foundation

/// `ClockProtocol` stub for SwiftUI previews. With `returnsImmediately = false`
/// (default) the cooldown loop suspends for ~24h, freezing the countdown at its
/// initial value — useful for the resting "cooldown active" state. Flip to `true`
/// to drain the cooldown instantly so previews render the post-countdown UI.
struct PreviewClock: ClockProtocol {
    var returnsImmediately: Bool = false

    func sleep(seconds: Int) async throws {
        if returnsImmediately { return }
        try await Task.sleep(for: .seconds(86400))
    }
}
#endif
