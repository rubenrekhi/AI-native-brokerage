import Foundation

@Observable
final class HomeViewModel {
    private let userProfileService: any UserProfileServiceProtocol
    private let chatService: any ChatServiceProtocol

    private(set) var greeting = ""
    private(set) var chats: [ChatItem] = []

    private(set) var isLoading = false
    private(set) var error: String?

    init(
        userProfileService: any UserProfileServiceProtocol = UserProfileService.shared,
        chatService: any ChatServiceProtocol = PlaceholderChatService.shared
    ) {
        self.userProfileService = userProfileService
        self.chatService = chatService
    }

    // MARK: - Contact URLs

    func founderPhoneURL() -> URL? { URL(string: "tel:4169189713") }
    func founderTextURL() -> URL? { URL(string: "sms:4169189713") }
    func contactEmailURL() -> URL? { URL(string: "mailto:admin@sevino.ai") }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            async let name = userProfileService.fetchPreferredName()
            async let recentChats = chatService.fetchRecentChats()
            let resolvedChats = try await recentChats
            // A failed name lookup falls back to a generic greeting rather than
            // blocking the rest of the home screen.
            let resolvedName: String? = try? await name
            greeting = Self.greeting(for: resolvedName, at: Date.now)
            chats = resolvedChats
        } catch let caughtError {
            error = caughtError.localizedDescription
        }
    }

    func clearError() {
        error = nil
    }

    private static func greeting(for name: String?, at date: Date) -> String {
        let hour = Calendar.current.component(.hour, from: date)
        if let name, !name.isEmpty {
            switch hour {
            case 5..<12: return L10n.Home.greetingMorning(name)
            case 12..<17: return L10n.Home.greetingAfternoon(name)
            default: return L10n.Home.greetingEvening(name)
            }
        }
        switch hour {
        case 5..<12: return L10n.Home.greetingMorningGeneric
        case 12..<17: return L10n.Home.greetingAfternoonGeneric
        default: return L10n.Home.greetingEveningGeneric
        }
    }
}
