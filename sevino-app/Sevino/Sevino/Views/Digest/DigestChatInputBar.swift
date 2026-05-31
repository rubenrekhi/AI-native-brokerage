import SwiftUI

struct DigestChatInputBar: View {
    let scale: CGFloat
    @Bindable var viewModel: DigestViewModel
    let onSubmit: () -> Void
    @FocusState private var isFocused: Bool

    private var hasText: Bool {
        !viewModel.chatText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        HStack(spacing: 10 * scale) {
            TextField(L10n.Digest.chatPlaceholder, text: $viewModel.chatText, axis: .vertical)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .lineLimit(1...4)
                .submitLabel(.send)
                .focused($isFocused)
                .onSubmit(submit)
                .padding(.horizontal, 14 * scale)
                .padding(.vertical, 11 * scale)
                .background(Color.sevinoSecondary.opacity(0.08), in: .rect(cornerRadius: 8 * scale))
                .accessibilityLabel(L10n.Digest.chatPlaceholder)

            Button(action: submit) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 15 * scale, weight: .semibold))
                    .foregroundStyle(hasText ? Color.sevinoPrimary : Color.sevinoSecondary.opacity(0.35))
                    .frame(width: 34 * scale, height: 34 * scale)
                    .background(hasText ? Color.sevinoSecondary : Color.sevinoSecondary.opacity(0.08), in: .circle)
            }
            .buttonStyle(.plain)
            .disabled(!hasText)
            .accessibilityLabel(L10n.Digest.sendAccessibility)
        }
        .padding(10 * scale)
        .modifier(SevinoGlass.card(cornerRadius: 8 * scale))
        .overlay {
            RoundedRectangle(cornerRadius: 8 * scale)
                .stroke(Color.sevinoSecondary.opacity(0.12), lineWidth: 1)
        }
        .shadow(color: .black.opacity(0.18), radius: 18 * scale, x: 0, y: 10 * scale)
    }

    private func submit() {
        guard hasText else { return }
        isFocused = false
        onSubmit()
    }
}

#Preview {
    let viewModel = DigestViewModel(client: PlaceholderDigestAPIClient())
    viewModel.chatText = "What changed here?"
    return ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        DigestChatInputBar(scale: 1, viewModel: viewModel, onSubmit: {})
            .padding()
    }
}
