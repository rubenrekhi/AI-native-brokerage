import SwiftUI

struct SidebarPanelView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL

    let scale: CGFloat
    let chats: [ChatItem]
    let founderPhoneURL: URL?
    let founderTextURL: URL?
    let contactEmailURL: URL?

    @State private var searchText = ""
    @State private var showContactOptions = false
    @State private var showFounderContact = false
    @State private var showSettings = false

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
                        ForEach(chats) { chat in
                            Button(action: {}) {
                                Text(chat.title)
                                    .font(.system(size: 16 * scale))
                                    .foregroundStyle(Color.sevinoSecondary)
                                    .lineLimit(1)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.vertical, 11 * scale)
                                    .padding(.horizontal, 12 * scale)
                                    .background(
                                        chat.id == chats.first?.id
                                            ? Color.sevinoGreyAccent.opacity(0.3)
                                            : .clear,
                                        in: .rect(cornerRadius: 8 * scale)
                                    )
                            }
                            .disabled(true)
                        }
                    }
                }
                .scrollIndicators(.hidden)
                .frame(maxHeight: .infinity, alignment: .top)

                HStack {
                    Button(action: { showSettings = true }) {
                        HStack(spacing: 6 * scale) {
                            Text(L10n.Sidebar.userName)
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

                    Button(L10n.Sidebar.newChatAccessibility, systemImage: "plus.circle", action: {})
                        .labelStyle(.iconOnly)
                        .font(.system(size: 24 * scale, weight: .light))
                        .foregroundStyle(Color.sevinoSecondary)
                        .frame(width: 44 * scale, height: 44 * scale)
                        .modifier(SevinoGlass.navCircle)
                        .disabled(true)
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
            .modifier(SevinoGlass.navCircle)
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
