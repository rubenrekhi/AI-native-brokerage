import SwiftUI

struct SidebarPanelView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL

    let scale: CGFloat
    let chats: [ChatItem]
    let userName: String?
    let founderPhoneURL: URL?
    let founderTextURL: URL?
    let contactEmailURL: URL?
    /// Conversation id of the chat currently rendered on the home surface,
    /// or `nil` when no conversation is active (fresh greeting state). The
    /// matching sidebar row gets the accent background so the user can see
    /// which thread is loaded.
    var activeConversationId: UUID? = nil
    /// Invoked when the user taps a sidebar row. Owner (`HomeView`) is
    /// responsible for calling `HomeViewModel.resume(conversationId:)` and
    /// dismissing the sidebar; this view just emits the intent.
    var onSelectChat: ((UUID) -> Void)? = nil
    var onNewChat: (() -> Void)? = nil
    var onDeleteChat: ((UUID) -> Void)? = nil

    @State private var searchText = ""
    @State private var showContactOptions = false
    @State private var showFounderContact = false
    @State private var showSettings = false

    private var filteredChats: [ChatItem] {
        guard !searchText.isEmpty else { return chats }
        return chats.filter { $0.title.localizedCaseInsensitiveContains(searchText) }
    }

    var body: some View {
        SevinoGlassContainer {
            ZStack {
                Color.sevinoSettingsBg
                    .ignoresSafeArea()

                VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Image(colorScheme == .dark ? "logo_white" : "logo_black")
                        .resizable()
                        .scaledToFit()
                        .frame(height: 36 * scale)
                        .accessibilityLabel(L10n.General.appName)

                    Spacer()

                    chatButton
                }
                .padding(.bottom, 20 * scale)

                HStack {
                    TextField(L10n.Sidebar.searchPlaceholder, text: $searchText)
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 16 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.horizontal, 14 * scale)
                .padding(.vertical, 12 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.3), in: .capsule)
                .padding(.bottom, 20 * scale)

                Text(L10n.Sidebar.chatsHeader)
                    .font(.system(size: 14 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoSecondary)
                    .padding(.bottom, 6 * scale)

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(filteredChats) { chat in
                            Button(action: { onSelectChat?(chat.conversationId) }) {
                                Text(chat.title)
                                    .font(.system(size: 16 * scale))
                                    .foregroundStyle(Color.sevinoSecondary)
                                    .lineLimit(1)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.vertical, 11 * scale)
                                    .padding(.horizontal, 12 * scale)
                                    .background(
                                        chat.conversationId == activeConversationId
                                            ? Color.sevinoGreyAccent.opacity(0.3)
                                            : .clear,
                                        in: .rect(cornerRadius: 8 * scale)
                                    )
                            }
                            .disabled(onSelectChat == nil)
                            .contextMenu {
                                if let onDeleteChat {
                                    Button(role: .destructive) {
                                        onDeleteChat(chat.conversationId)
                                    } label: {
                                        Label(L10n.Sidebar.deleteChat, systemImage: "trash")
                                    }
                                }
                            }
                        }
                    }
                }
                .scrollIndicators(.hidden)
                .frame(maxHeight: .infinity, alignment: .top)

                HStack {
                    Button(action: { showSettings = true }) {
                        HStack(spacing: 6 * scale) {
                            Text(userName ?? L10n.Sidebar.accountPillFallback)
                                .font(.system(size: 15 * scale, weight: .medium))
                                .foregroundStyle(Color.sevinoSecondary)

                            Image(systemName: "chevron.down")
                                .font(.system(size: 11 * scale, weight: .semibold))
                                .foregroundStyle(Color.sevinoSecondary)
                                .accessibilityHidden(true)
                        }
                        .padding(.horizontal, 16 * scale)
                        .padding(.vertical, 10 * scale)
                    }
                    .modifier(SevinoGlass.chip)
                    .fullScreenCover(isPresented: $showSettings) {
                        SettingsView()
                    }

                    Spacer()

                    Button(L10n.Sidebar.newChatAccessibility, systemImage: "plus.circle") {
                        onNewChat?()
                    }
                    .labelStyle(.iconOnly)
                    .font(.system(size: 24 * scale, weight: .light))
                    .foregroundStyle(Color.sevinoSecondary)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .modifier(SevinoGlass.navCircleClear)
                }
                .padding(.bottom, 8 * scale)
            }
                .padding(.horizontal, 14 * scale)
                .padding(.top, 16 * scale)
                .frame(width: 300 * scale, alignment: .leading)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            }
        }
    }

    private var chatButton: some View {
        Button(L10n.Sidebar.chatAccessibility, systemImage: "message", action: { showContactOptions = true })
            .labelStyle(.iconOnly)
            .font(.system(size: 16 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoSecondary)
            .frame(width: 44 * scale, height: 44 * scale)
            .modifier(SevinoGlass.navCircleClear)
            .confirmationDialog(L10n.Sidebar.contactTitle, isPresented: $showContactOptions) {
                Button(L10n.Sidebar.talkToFounders, action: { showFounderContact = true })
                Button(L10n.Sidebar.contactUs, action: openEmail)
            }
            .confirmationDialog(L10n.Sidebar.talkToFounders, isPresented: $showFounderContact) {
                Button(L10n.Sidebar.callFounders, action: callFounders)
                Button(L10n.Sidebar.textFounders, action: textFounders)
            }
    }

    private func callFounders() {
        guard let url = founderPhoneURL else { return }
        openURL(url)
    }

    private func textFounders() {
        guard let url = founderTextURL else { return }
        openURL(url)
    }

    private func openEmail() {
        guard let url = contactEmailURL else { return }
        openURL(url)
    }
}
