import Foundation
@testable import Sevino

final class MockShortcutsAPIClient: ShortcutsAPIClientProtocol, @unchecked Sendable {
    var shortcutsToReturn: [Shortcut] = []
    var fetchError: Error?

    private(set) var fetchShortcutsCallCount = 0

    func fetchShortcuts() async throws -> [Shortcut] {
        fetchShortcutsCallCount += 1
        if let fetchError { throw fetchError }
        return shortcutsToReturn
    }
}
