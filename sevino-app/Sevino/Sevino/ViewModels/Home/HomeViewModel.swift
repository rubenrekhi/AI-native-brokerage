import Foundation

@Observable
final class HomeViewModel {
    private(set) var greeting = ""

    // MARK: - Sidebar mock chats
    // TODO: Replace with real chat history from backend
    private(set) var mockChats = [
        ChatItem(title: "How was Tesla's most recent e..."),
        ChatItem(title: "Help me balance my portfolio"),
        ChatItem(title: "What happened with AMD this..."),
        ChatItem(title: "What is an option?"),
        ChatItem(title: "How much would I have made ..."),
    ]

    // MARK: - Contact URLs

    func founderPhoneURL() -> URL? { URL(string: "tel:4169189713") }
    func founderTextURL() -> URL? { URL(string: "sms:4169189713") }
    func contactEmailURL() -> URL? { URL(string: "mailto:admin@sevino.ai") }

    func loadGreeting() {
        let hour = Calendar.current.component(.hour, from: Date.now)
        let name = "Riley"
        switch hour {
        case 5..<12: greeting = L10n.Home.greetingMorning(name)
        case 12..<17: greeting = L10n.Home.greetingAfternoon(name)
        default: greeting = L10n.Home.greetingEvening(name)
        }
    }
}
