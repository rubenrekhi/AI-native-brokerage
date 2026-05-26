import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

struct HomeChatInputBar: View {
    @Bindable var viewModel: TickerMentionViewModel
    let scale: CGFloat
    let isDimmed: Bool
    var isStreaming: Bool = false
    let onSend: ([MessageSegment]) -> Void
    let onQuickCommands: () -> Void
    @FocusState private var isFocused: Bool
    @State private var selection = AttributedTextSelection()
    @State private var showDiscoverPrompt = false
    @State private var inputVM: HomeChatInputViewModel

    init(
        viewModel: TickerMentionViewModel,
        scale: CGFloat,
        isDimmed: Bool,
        isStreaming: Bool = false,
        onSend: @escaping ([MessageSegment]) -> Void,
        onQuickCommands: @escaping () -> Void,
        inputViewModel: HomeChatInputViewModel? = nil
    ) {
        self.viewModel = viewModel
        self.scale = scale
        self.isDimmed = isDimmed
        self.isStreaming = isStreaming
        self.onSend = onSend
        self.onQuickCommands = onQuickCommands
        _inputVM = State(initialValue: inputViewModel ?? HomeChatInputViewModel(mention: viewModel))
    }

    private var hasText: Bool {
        !viewModel.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var attributedTextBinding: Binding<AttributedString> {
        Binding(
            get: { TickerMentionAttributedText.make(text: viewModel.text, tokens: viewModel.tokens, scale: scale) },
            set: { viewModel.updateText(String($0.characters)) }
        )
    }

    private var alertPresented: Binding<Bool> {
        Binding(
            get: { inputVM.alert != nil },
            set: { if !$0 { inputVM.alert = nil } }
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            TextEditor(text: attributedTextBinding, selection: $selection)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .scrollContentBackground(.hidden)
                .focused($isFocused)
                .frame(minHeight: 20 * scale, maxHeight: 100 * scale)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 16 * scale)
                .padding(.top, 14 * scale)
                .padding(.bottom, 8 * scale)
                .accessibilityLabel(L10n.Home.chatPlaceholder)
                .overlay(alignment: .topLeading) {
                    if viewModel.text.isEmpty {
                        Text(L10n.Home.chatPlaceholder)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.homePlaceholder)
                            .padding(.leading, 16 * scale + 5)
                            .padding(.top, 14 * scale + 8)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    } else if showDiscoverPrompt && viewModel.text == "$" {
                        HStack(spacing: 0) {
                            Text(verbatim: "$")
                                .font(.system(size: 16 * scale))
                                .hidden()
                            Text(L10n.Home.quickCommandsDiscoverPlaceholder)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.homePlaceholder)
                        }
                        .padding(.leading, 16 * scale + 5)
                        .padding(.top, 14 * scale + 8)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                    }
                }

            HStack(spacing: 0) {
                Button(L10n.Home.quickCommandsButtonAccessibility, systemImage: "plus", action: onQuickCommands)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 18 * scale, weight: .medium))
                    .foregroundStyle(Color.sevinoGreyContrast)
                    .frame(width: 44 * scale, height: 44 * scale)

                Spacer()

                Button(
                    inputVM.isRecording ? L10n.Home.micStopAccessibility : L10n.Home.micAccessibility,
                    systemImage: inputVM.isRecording ? "mic.fill" : "mic",
                    action: toggleDictation
                )
                .labelStyle(.iconOnly)
                .font(.system(size: 18 * scale, weight: .medium))
                .foregroundStyle(inputVM.isRecording ? Color.sevinoNegative : Color.sevinoGreyContrast)
                .frame(width: 44 * scale, height: 44 * scale)
                .accessibilityValue(inputVM.isRecording ? L10n.Home.micRecordingState : "")
                .accessibilityHint(inputVM.isRecording ? L10n.Home.micStopHint : L10n.Home.micStartHint)

                Button(L10n.Home.sendAccessibility, systemImage: "arrow.up", action: sendMessage)
                    .labelStyle(.iconOnly)
                    .font(.system(size: 16 * scale, weight: .semibold))
                    .foregroundStyle(hasText ? Color.sevinoPrimary : Color.sevinoGreyAccent)
                    .frame(width: 30 * scale, height: 30 * scale)
                    .background(hasText ? Color.sevinoSecondary : .clear, in: .circle)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .disabled(!hasText || isStreaming)
            }
            .padding(.horizontal, 14 * scale)
            .padding(.bottom, 8 * scale)
        }
        .modifier(SevinoGlass.card)
        .onChange(of: isDimmed) { _, newValue in
            if newValue {
                isFocused = false
                viewModel.dismiss()
                inputVM.stopIfRecording()
            }
        }
        .onChange(of: viewModel.caretToEndTick) { _, _ in
            let attr = TickerMentionAttributedText.make(text: viewModel.text, tokens: viewModel.tokens, scale: scale)
            selection = AttributedTextSelection(insertionPoint: attr.endIndex)
        }
        .onChange(of: viewModel.focusRequestTick) { _, _ in
            isFocused = true
            showDiscoverPrompt = viewModel.text == "$"
            let attr = TickerMentionAttributedText.make(text: viewModel.text, tokens: viewModel.tokens, scale: scale)
            selection = AttributedTextSelection(insertionPoint: attr.endIndex)
        }
        .onChange(of: viewModel.text) { _, newValue in
            if newValue != "$" { showDiscoverPrompt = false }
        }
        .alert(L10n.Home.dictationPermissionTitle, isPresented: alertPresented) {
            #if canImport(UIKit)
            Button(L10n.Home.dictationOpenSettings) { openAppSettings() }
            #endif
            Button(L10n.Home.dictationDismiss, role: .cancel) {}
        } message: {
            Text(inputVM.alert?.message ?? "")
        }
    }

    private func sendMessage() {
        guard hasText else { return }
        inputVM.stopIfRecording()
        onSend(viewModel.makeSegments())
    }

    private func toggleDictation() {
        if !inputVM.isRecording { isFocused = false }
        inputVM.toggleDictation()
    }

    #if canImport(UIKit)
    private func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
    #endif
}

#Preview("Empty") {
    HomeChatInputBar(
        viewModel: TickerMentionViewModel(),
        scale: 1,
        isDimmed: false,
        onSend: { _ in },
        onQuickCommands: {}
    )
    .padding()
}

#Preview("With text") {
    let viewModel = TickerMentionViewModel()
    viewModel.updateText("Hello")
    return HomeChatInputBar(
        viewModel: viewModel,
        scale: 1,
        isDimmed: false,
        onSend: { _ in },
        onQuickCommands: {}
    )
    .padding()
}

#Preview("Dimmed") {
    let viewModel = TickerMentionViewModel()
    viewModel.updateText("Hello")
    return HomeChatInputBar(
        viewModel: viewModel,
        scale: 1,
        isDimmed: true,
        onSend: { _ in },
        onQuickCommands: {}
    )
    .padding()
}
