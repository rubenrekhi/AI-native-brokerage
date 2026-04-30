import SwiftUI

/// Six-box OTP input with a hidden `TextField` overlay so iOS SMS auto-fill
/// (`textContentType(.oneTimeCode)`) and clipboard paste work for free.
///
/// The visible row of liquid-glass boxes mirrors `code` one digit at a time;
/// the next-empty box gets a brighter stroke to show where the next digit lands.
/// When `errorState` is true every box gets a red stroke instead. Tapping
/// anywhere in the row focuses the hidden field and brings the keyboard up.
///
/// Inputs are filtered to digits and capped at 6 inside the view, so callers
/// can pass a binding directly without pre-sanitizing. The filtered value is
/// echoed back through both the binding and `onCodeChange`, letting consumers
/// react to "code completed" without observing the binding themselves.
struct OTPInputView: View {
    @Binding var code: String
    let scale: CGFloat
    let errorState: Bool
    /// Localized VoiceOver hint announced when the input gets focus. Required
    /// (no default) so the phone vs. email channel is explicit at the call site —
    /// VoiceOver users on the email screen would otherwise hear "we sent to your
    /// phone" verbatim.
    let accessibilityHint: String
    let onCodeChange: (String) -> Void

    @FocusState private var isFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    static let digitCount: Int = 6
    static let boxWidth: CGFloat = 46
    static let boxHeight: CGFloat = 56
    static let boxSpacing: CGFloat = 8

    var body: some View {
        ZStack {
            hiddenInputField
            boxRow
        }
        .contentShape(.rect)
        .onTapGesture { isFocused = true }
    }

    private var hiddenInputField: some View {
        TextField("", text: $code)
            .keyboardType(.numberPad)
            .textContentType(.oneTimeCode)
            .focused($isFocused)
            .frame(width: 1, height: 1)
            .opacity(0.001)
            .accessibilityLabel(L10n.Auth.otpInputA11yLabel)
            .accessibilityHint(accessibilityHint)
            .accessibilityValue(Text(code).speechSpellsOutCharacters())
            .onChange(of: code) { _, newValue in
                let filtered = Self.sanitize(newValue)
                if filtered != newValue {
                    // Re-entry of `onChange` will hit the else branch and fire once.
                    code = filtered
                } else {
                    onCodeChange(filtered)
                }
            }
            // Pop the numeric keyboard the moment the screen appears so the user
            // can start typing immediately. `@AccessibilityFocusState` only drives
            // VoiceOver — the @FocusState here is what actually raises the keyboard.
            .onAppear { isFocused = true }
    }

    /// Strips non-digit characters and caps the length at `digitCount`.
    /// Hoisted out of the `onChange` closure so the rule is unit-testable.
    static func sanitize(_ raw: String) -> String {
        String(raw.filter(\.isNumber).prefix(digitCount))
    }

    private var boxRow: some View {
        HStack(spacing: Self.boxSpacing * scale) {
            ForEach(0..<Self.digitCount, id: \.self) { index in
                OTPBoxView(
                    digit: digit(at: index),
                    isFocused: isFocused && index == focusedIndex,
                    errorState: errorState,
                    showCursor: shouldShowCursor(at: index),
                    reduceMotion: reduceMotion,
                    scale: scale
                )
                .accessibilityHidden(true)
            }
        }
    }

    private var focusedIndex: Int {
        min(code.count, Self.digitCount - 1)
    }

    private func digit(at index: Int) -> String? {
        guard index < code.count else { return nil }
        let stringIndex = code.index(code.startIndex, offsetBy: index)
        return String(code[stringIndex])
    }

    private func shouldShowCursor(at index: Int) -> Bool {
        isFocused && index == code.count && code.count < Self.digitCount
    }
}

// MARK: - OTP Box

private struct OTPBoxView: View {
    let digit: String?
    let isFocused: Bool
    let errorState: Bool
    let showCursor: Bool
    let reduceMotion: Bool
    let scale: CGFloat

    var body: some View {
        ZStack {
            content
        }
        .frame(
            width: OTPInputView.boxWidth * scale,
            height: OTPInputView.boxHeight * scale
        )
        .modifier(SevinoGlass.card)
        .overlay(strokeOverlay)
    }

    @ViewBuilder
    private var content: some View {
        if let digit {
            Text(digit)
                .font(.system(size: 22 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
        } else if showCursor {
            BlinkingCursorView(reduceMotion: reduceMotion, scale: scale)
        }
    }

    private var strokeOverlay: some View {
        RoundedRectangle(cornerRadius: CardGlass.cornerRadius)
            .strokeBorder(strokeColor, lineWidth: strokeWidth)
    }

    private var strokeColor: Color {
        if errorState { return Color.sevinoNegative }
        if isFocused { return Color.welcomeText.opacity(0.85) }
        return .clear
    }

    private var strokeWidth: CGFloat {
        (errorState || isFocused) ? 1.5 * scale : 0
    }
}

// MARK: - Cursor

/// Thin vertical bar shown inside the next-empty box while the input is focused.
/// Blinks at ~0.6s when motion is allowed; stays solid for Reduce Motion users.
private struct BlinkingCursorView: View {
    let reduceMotion: Bool
    let scale: CGFloat

    @State private var dimmed: Bool = false

    var body: some View {
        Rectangle()
            .fill(Color.welcomeText)
            .frame(width: 2 * scale, height: 22 * scale)
            .opacity(dimmed ? 0 : 1)
            .onAppear {
                guard !reduceMotion else { return }
                withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                    dimmed = true
                }
            }
    }
}

// MARK: - Previews

#Preview("Empty") {
    OTPInputViewPreviewWrapper(initial: "")
}

#Preview("Partial") {
    OTPInputViewPreviewWrapper(initial: "123")
}

#Preview("Full") {
    OTPInputViewPreviewWrapper(initial: "123456")
}

#Preview("Error") {
    OTPInputViewPreviewWrapper(initial: "999999", errorState: true)
}

private struct OTPInputViewPreviewWrapper: View {
    @State private var code: String
    private let errorState: Bool

    init(initial: String, errorState: Bool = false) {
        self._code = State(initialValue: initial)
        self.errorState = errorState
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            OTPInputView(
                code: $code,
                scale: 1,
                errorState: errorState,
                accessibilityHint: L10n.Auth.otpInputA11yHintPhone,
                onCodeChange: { _ in }
            )
        }
        .preferredColorScheme(.dark)
    }
}
