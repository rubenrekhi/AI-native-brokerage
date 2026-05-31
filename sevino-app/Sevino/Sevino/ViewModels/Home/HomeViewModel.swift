import Foundation

@Observable
final class HomeViewModel {
    private let userProfileService: any UserProfileServiceProtocol
    private let chatService: any RecentChatsServiceProtocol
    /// Factory used by `resume(conversationId:)` to construct the swapped
    /// store. Production wires this to the default `ConversationStore`
    /// init (real `APIClient` / `SSEClient`); tests stub it to control the
    /// loaded transcript and avoid hitting the real network.
    private let conversationStoreFactory: @MainActor (UUID) -> ConversationStore
    /// Active conversation store. Mutated by `resume(conversationId:)` —
    /// the property is `private(set)` so views observe the swap but can't
    /// reach in to construct a new store themselves.
    private(set) var conversationStore: ConversationStore

    var messages: [Message] { conversationStore.messages }
    var turnState: ConversationStore.TurnState { conversationStore.state }
    var isConversationActive: Bool { !conversationStore.messages.isEmpty }

    private(set) var greeting = ""
    private(set) var preferredName: String?
    private(set) var chats: [ChatItem] = []

    private(set) var isLoading = false
    private(set) var error: String?
    /// Surfaced when `resume(conversationId:)` can't load the persisted
    /// transcript (transport error, 4xx, decode failure). Views observe
    /// this on `HomeView` and present a one-button alert so the user
    /// isn't left with the sidebar closed and no feedback.
    private(set) var resumeError: String?

    // `conversationStore` is an Optional with a nil default rather than
    // `= ConversationStore()` because the latter triggers a "call to
    // main actor-isolated initializer in a synchronous nonisolated context"
    // error — Swift evaluates init default args without inheriting the
    // enclosing actor isolation. Tests pass an explicit store; production
    // gets the lazy MainActor-isolated default below.
    init(
        userProfileService: any UserProfileServiceProtocol = UserProfileService.shared,
        chatService: any RecentChatsServiceProtocol = LiveRecentChatsService.shared,
        conversationStore: ConversationStore? = nil,
        conversationStoreFactory: (@MainActor (UUID) -> ConversationStore)? = nil
    ) {
        self.userProfileService = userProfileService
        self.chatService = chatService
        self.conversationStore = conversationStore ?? ConversationStore()
        self.conversationStoreFactory =
            conversationStoreFactory ?? { ConversationStore(conversationId: $0) }
    }

    func send(
        text: String,
        context: [String: JSONValue]? = nil,
        digestCard: ChatDigestCard? = nil,
        attachedContext: AttachedContext? = nil
    ) async throws {
        try await conversationStore.send(
            text: text,
            context: context,
            digestCard: digestCard,
            attachedContext: attachedContext
        )
    }

    /**
     Resume a previously-persisted conversation in the chat surface.

     Swaps `conversationStore` for a fresh instance bound to the given
     conversation id, then calls `load()` to populate it from the
     `GET /v1/conversations/{id}/messages` endpoint. After the await
     resolves, `isConversationActive` flips to `true` (assuming the
     transcript is non-empty) and the chat surface overlay renders the
     loaded history.

     Throws on transport / decode failures so the sidebar can surface an
     error without leaving the home screen in a half-swapped state — the
     new store still owns the failed-load `state = .error(...)`, but
     `isConversationActive` stays `false`, so the chat overlay won't
     appear.
     */
    func resume(conversationId: UUID) async {
        // Load the transcript *before* swapping the live store so the home
        // surface keeps rendering the previous conversation throughout the
        // sidebar's spring animation. Swapping first causes a visible flicker:
        // messages briefly drops to [] (showing the greeting), then the new
        // chat pops in mid-animation at a different offset, which reads as
        // choppy when the user taps a sidebar row. Loading first means the
        // user sees old chat → new chat as a single, clean transition once
        // the sidebar finishes closing.
        //
        // On failure, the store stays as-is — the user gets the resume-error
        // alert and the previous chat is still visible. That's the right UX:
        // a failed resume shouldn't blank the screen.
        resumeError = nil
        let store = conversationStoreFactory(conversationId)
        do {
            try await store.load()
            conversationStore = store
        } catch {
            resumeError = error.localizedDescription
        }
    }

    func startNewConversation() {
        conversationStore = ConversationStore()
    }

    func deleteConversation(_ id: UUID) async {
        let removed = chats.filter { $0.conversationId == id }
        chats.removeAll { $0.conversationId == id }
        if conversationStore.conversationId == id {
            conversationStore = ConversationStore()
        }
        do {
            try await chatService.deleteConversation(id)
        } catch {
            chats.append(contentsOf: removed)
            self.error = error.localizedDescription
        }
    }

    func refreshChats() async {
        do {
            chats = try await chatService.fetchRecentChats()
        } catch {
            // Stale sidebar is acceptable; don't surface this error.
        }
    }

    func clearResumeError() {
        resumeError = nil
    }

    // MARK: - Contact URLs

    func founderPhoneURL() -> URL? { AppConfig.Contact.founderPhoneURL }
    func founderTextURL() -> URL? { AppConfig.Contact.founderTextURL }
    func contactEmailURL() -> URL? { AppConfig.Contact.supportEmailURL }

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
            preferredName = resolvedName?.isEmpty == false ? resolvedName : nil
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
