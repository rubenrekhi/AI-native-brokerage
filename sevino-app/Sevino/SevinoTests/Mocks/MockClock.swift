import Foundation
@testable import Sevino

/// Test clock that records every sleep duration. Returns instantly by default so
/// the cooldown loop drains via `await vm.cooldownTask?.value` in the same MainActor
/// frame; flip `pauseSleeps = true` to suspend each sleep until the surrounding
/// task is canceled — useful for asserting "in flight" cooldown state.
final class MockClock: ClockProtocol {
    private(set) var sleepCalls: [Int] = []
    var pauseSleeps: Bool = false

    func sleep(seconds: Int) async throws {
        sleepCalls.append(seconds)
        if pauseSleeps {
            try await Task.sleep(for: .seconds(86400))
        }
    }
}
