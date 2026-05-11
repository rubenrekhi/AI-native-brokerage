import XCTest
@testable import Sevino

@MainActor
final class HomeViewModelTests: XCTestCase {

    private var mockProfile: MockUserProfileService!
    private var mockChat: MockRecentChatsService!
    private var viewModel: HomeViewModel!

    override func setUp() {
        mockProfile = MockUserProfileService()
        mockChat = MockRecentChatsService()
        viewModel = HomeViewModel(
            userProfileService: mockProfile,
            chatService: mockChat
        )
    }

    // MARK: - Greeting with name

    func testLoadWithPreferredNameSetsPersonalizedGreeting() async {
        mockProfile.preferredName = "Riley"

        await viewModel.load()

        XCTAssertTrue(
            viewModel.greeting.contains("Riley"),
            "greeting should include the fetched name, got \(viewModel.greeting)"
        )
        XCTAssertEqual(viewModel.preferredName, "Riley")
        XCTAssertNil(viewModel.error)
    }

    // MARK: - preferredName exposure

    func testLoadWhenNameIsNilLeavesPreferredNameNil() async {
        mockProfile.preferredName = nil

        await viewModel.load()

        XCTAssertNil(viewModel.preferredName)
    }

    func testLoadWhenNameIsEmptyStringLeavesPreferredNameNil() async {
        mockProfile.preferredName = ""

        await viewModel.load()

        XCTAssertNil(viewModel.preferredName)
    }

    func testLoadWhenNameFetchFailsLeavesPreferredNameNil() async {
        mockProfile.fetchPreferredNameError = NSError(domain: "test", code: 0)

        await viewModel.load()

        XCTAssertNil(viewModel.preferredName)
    }

    // MARK: - Greeting fallback

    func testLoadWhenNameIsNilUsesGenericGreeting() async {
        mockProfile.preferredName = nil

        await viewModel.load()

        XCTAssertEqual(
            viewModel.greeting,
            Self.expectedGenericGreeting(),
            "nil name should fall back to generic greeting"
        )
        XCTAssertNil(viewModel.error)
    }

    func testLoadWhenNameIsEmptyStringUsesGenericGreeting() async {
        mockProfile.preferredName = ""

        await viewModel.load()

        XCTAssertEqual(
            viewModel.greeting,
            Self.expectedGenericGreeting(),
            "empty name should fall back to generic greeting"
        )
    }

    func testLoadWhenNameFetchFailsUsesGenericGreetingAndStillLoadsChats() async {
        mockProfile.fetchPreferredNameError = NSError(domain: "test", code: 0)
        mockChat.chats = [
            ChatItem(
                conversationId: UUID(),
                title: "Chat 1",
                lastMessageAt: .now
            )
        ]

        await viewModel.load()

        XCTAssertEqual(
            viewModel.greeting,
            Self.expectedGenericGreeting(),
            "name fetch failure should fall back to generic greeting"
        )
        XCTAssertEqual(viewModel.chats.count, 1, "chats should still load when name fetch fails")
        XCTAssertNil(viewModel.error, "name failures should not surface a user-facing error")
    }

    // MARK: - Chats error propagation

    func testLoadWhenChatFetchFailsSurfacesError() async {
        mockProfile.preferredName = "Riley"
        mockChat.fetchRecentChatsError = NSError(
            domain: "test", code: 0,
            userInfo: [NSLocalizedDescriptionKey: "Network error"]
        )

        await viewModel.load()

        XCTAssertEqual(viewModel.error, "Network error")
        XCTAssertTrue(viewModel.chats.isEmpty)
    }

    // MARK: - clearError

    func testClearErrorRemovesError() async {
        mockChat.fetchRecentChatsError = NSError(domain: "test", code: 0)
        await viewModel.load()
        XCTAssertNotNil(viewModel.error)

        viewModel.clearError()

        XCTAssertNil(viewModel.error)
    }

    // MARK: - Helpers

    /// Mirrors `HomeViewModel.greeting(for:at:)` for the current hour with a nil name.
    private static func expectedGenericGreeting() -> String {
        let hour = Calendar.current.component(.hour, from: .now)
        switch hour {
        case 5..<12: return L10n.Home.greetingMorningGeneric
        case 12..<17: return L10n.Home.greetingAfternoonGeneric
        default: return L10n.Home.greetingEveningGeneric
        }
    }
}
