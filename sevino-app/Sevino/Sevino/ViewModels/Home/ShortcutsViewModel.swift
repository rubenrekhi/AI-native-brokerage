import Foundation
import os.log

@Observable
final class ShortcutsViewModel {
    private static let logger = Logger(subsystem: "ai.sevino.Sevino", category: "ShortcutsViewModel")

    private(set) var shortcuts: [Shortcut] = []
    private(set) var isLoading = false

    var topShortcuts: [Shortcut] { Array(shortcuts.prefix(3)) }
    var overflowShortcuts: [Shortcut] { Array(shortcuts.dropFirst(3)) }
    var hasOverflow: Bool { shortcuts.count > 3 }

    private let client: any ShortcutsAPIClientProtocol

    init(client: any ShortcutsAPIClientProtocol = ShortcutsAPIClient()) {
        self.client = client
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            shortcuts = try await client.fetchShortcuts()
        } catch {
            shortcuts = []
            Self.logger.error("Failed to load shortcuts: \(String(describing: error), privacy: .public)")
        }
    }
}
