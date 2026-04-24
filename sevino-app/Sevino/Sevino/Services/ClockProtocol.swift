import Foundation

/// Abstracts a sleep operation so view-models that drive timers can be tested
/// deterministically. `SystemClock` wraps `Task.sleep` for production use; tests
/// inject `MockClock` (`SevinoTests/Mocks/MockClock.swift`) to record sleep
/// durations and either return instantly or hold the sleep until canceled.
protocol ClockProtocol: Sendable {
    func sleep(seconds: Int) async throws
}

struct SystemClock: ClockProtocol {
    func sleep(seconds: Int) async throws {
        try await Task.sleep(for: .seconds(seconds))
    }
}
