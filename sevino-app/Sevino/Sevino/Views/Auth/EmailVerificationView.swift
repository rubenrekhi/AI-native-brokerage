#if DEBUG
import Auth
#endif
import SwiftUI

/// Email OTP entry screen.
///
/// Owns an `EmailVerificationViewModel` for the lifetime of the view and threads
/// its state into:
/// - the `OTPInputView` (boxes auto-submit on the 6th digit through the VM)
/// - the resend pill / live-countdown caption
/// - the alert presented when `vm.error` flips non-nil
///
/// Lifecycle:
/// 1. `.task` fires `vm.onAppear()` once on appear — primes the 15s resend
///    cooldown. Supabase auto-sends the confirmation OTP as a side effect of
///    `signUp`, so this view never makes a network call on entry.
///    Re-entry from SwiftUI's `.task` is gated inside the VM.
/// 2. Local `otpInput` state is the binding the boxes read/write; we mirror it
///    to `vm.otp` via `onCodeChange` so the canonical value lives on the VM,
///    but reads stay synchronous from SwiftUI's perspective.
/// 3. On a successful verify the Supabase `userUpdated` event flips
///    `AuthService.isEmailVerified`, which `vm.isVerified` reads reactively.
///    `onChange(of: vm.isVerified)` then advances the route via `onVerified()`.
///    On a back-tap we hand off to `onChangeEmail()` so the parent can sign
///    out / route the user back to entry — Supabase doesn't allow editing
///    the email of an unverified account in place.
struct EmailVerificationView: View {
    private let onVerified: () -> Void
    private let onChangeEmail: () -> Void

    @State private var vm: EmailVerificationViewModel
    @State private var otpInput: String = ""
    @State private var scale: CGFloat = 1
    @AccessibilityFocusState private var otpFieldFocused: Bool

    init(
        email: String,
        authService: any AuthServiceProtocol = AuthService.shared,
        clock: any ClockProtocol = SystemClock(),
        onVerified: @escaping () -> Void,
        onChangeEmail: @escaping () -> Void
    ) {
        self.onVerified = onVerified
        self.onChangeEmail = onChangeEmail
        _vm = State(wrappedValue: EmailVerificationViewModel(
            email: email,
            authService: authService,
            clock: clock
        ))
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                AuthHeaderView(scale: scale, onBack: onChangeEmail)
                ScrollView {
                    VStack(spacing: 0) {
                        titleSection
                        otpSection
                        nextButton
                        resendSection
                    }
                }
                .scrollIndicators(.hidden)
                Spacer(minLength: 0)
            }
        }
        .background { AuthBackgroundView() }
        .preferredColorScheme(.dark)
        .background(scaleAnchor)
        .task {
            vm.onAppear()
            otpFieldFocused = true
        }
        .onChange(of: vm.isVerified) { _, verified in
            if verified { onVerified() }
        }
        .onChange(of: vm.otp) { _, newValue in
            // Keep the local binding in lockstep with the VM after it filters
            // (e.g. a paste sanitizes from "ABC123" → "123" inside the VM).
            if newValue != otpInput {
                otpInput = newValue
            }
        }
        .alert(
            L10n.General.errorTitle,
            isPresented: errorPresented,
            presenting: vm.error
        ) { _ in
            Button(L10n.General.ok, action: vm.clearError)
        } message: { error in
            Text(error.errorDescription ?? "")
        }
        // Only buzz on the nil → error transition; the error → nil transition
        // happens when the user taps OK to dismiss the alert and shouldn't fire
        // a second haptic on what is otherwise an acknowledgment tap.
        .sensoryFeedback(.error, trigger: vm.error) { _, new in new != nil }
        .sensoryFeedback(.success, trigger: vm.isVerified)
    }

    // MARK: - Sections

    private var titleSection: some View {
        VStack(spacing: 8 * scale) {
            // Two stacked Text views (instead of a single string with `\n`) so
            // dynamic-type and translation can wrap each line independently.
            // Combined into one accessibility element so VoiceOver reads the
            // phrase continuously rather than as two unrelated swipes.
            VStack(spacing: 0) {
                Text(L10n.Auth.emailVerifyTitle)
                    .font(.dmSerif(size: 28 * scale))
                    .foregroundStyle(Color.welcomeText)
                    .multilineTextAlignment(.center)
                Text(vm.email)
                    .font(.dmSerif(size: 28 * scale))
                    .foregroundStyle(Color.welcomeText)
                    .multilineTextAlignment(.center)
                    // Worst-case 50+ char emails wrap to a second line; middle
                    // truncation keeps both the local-part start and the TLD
                    // visible (e.g. `verylong…example.co.uk`) so the user can
                    // still verify they typed the right address.
                    .lineLimit(2)
                    .minimumScaleFactor(0.7)
                    .truncationMode(.middle)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(L10n.Auth.emailVerifyTitle) \(vm.email)")
            .accessibilityIdentifier("emailVerification.title")

            Text(L10n.Auth.emailVerifySubtitle)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeTextSecondary)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("emailVerification.subtitle")
        }
        .padding(.top, 32 * scale)
        .padding(.horizontal, 24 * scale)
    }

    private var otpSection: some View {
        OTPInputView(
            code: $otpInput,
            scale: scale,
            errorState: isOTPRejected,
            accessibilityHint: L10n.Auth.otpInputA11yHintEmail,
            onCodeChange: { value in
                Task { await vm.updateOTP(value) }
            }
        )
        .accessibilityFocused($otpFieldFocused)
        .padding(.top, 32 * scale)
        .padding(.horizontal, 32 * scale)
    }

    private var nextButton: some View {
        Button(action: { Task { await vm.confirmOTP() } }) {
            Group {
                if vm.isConfirming {
                    ProgressView()
                        .tint(Color.welcomeButtonDarkTint)
                } else {
                    Text(L10n.Auth.otpNext)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.welcomeButtonDarkTint)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14 * scale)
            .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(tint: Color.welcomeButtonLightTint.opacity(0.4)))
        .disabled(!vm.isOTPComplete || vm.isConfirming || vm.isVerified)
        .opacity((vm.isOTPComplete || vm.isConfirming) ? 1 : 0.6)
        .padding(.top, 20 * scale)
        .padding(.horizontal, 32 * scale)
        .accessibilityIdentifier("emailVerification.next")
    }

    private var resendSection: some View {
        HStack(spacing: 6 * scale) {
            Text(L10n.Auth.otpResendPrompt)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.welcomeTextSecondary)

            if vm.canResend {
                Button { Task { await vm.resendOTP() } } label: {
                    Text(L10n.Auth.otpResend)
                        .font(.system(size: 14 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                        .underline()
                        .frame(minHeight: 44 * scale)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("emailVerification.resend")
            } else {
                Text(L10n.Auth.otpResendCountdown(vm.secondsRemaining))
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(minHeight: 44 * scale)
                    .accessibilityIdentifier("emailVerification.resendCountdown")
            }
        }
        .padding(.top, 12 * scale)
    }

    private var scaleAnchor: some View {
        GeometryReader { geo in
            Color.clear.onAppear {
                scale = geo.size.width / 393
            }
        }
    }

    /// True only for the validation-rejection branches — `.network` /
    /// `.sendFailed` are infrastructure errors and shouldn't paint the OTP
    /// boxes red since the entered code may still be valid.
    private var isOTPRejected: Bool {
        vm.error == .invalidCode || vm.error == .expired
    }

    private var errorPresented: Binding<Bool> {
        Binding(
            get: { vm.error != nil },
            set: { if !$0 { vm.clearError() } }
        )
    }
}

// MARK: - Previews

#if DEBUG
#Preview("Idle") {
    EmailVerificationView(
        email: "readyriley@sevino.ai",
        authService: PreviewAuthService(isAuthenticated: true),
        clock: PreviewClock(),
        onVerified: {},
        onChangeEmail: {}
    )
}

#Preview("Resend ready") {
    EmailVerificationView(
        email: "readyriley@sevino.ai",
        authService: PreviewAuthService(isAuthenticated: true),
        clock: PreviewClock(returnsImmediately: true),
        onVerified: {},
        onChangeEmail: {}
    )
}

#Preview("Long email") {
    EmailVerificationView(
        email: "verylongemailaddress+work@subdomain.example.co.uk",
        authService: PreviewAuthService(isAuthenticated: true),
        clock: PreviewClock(),
        onVerified: {},
        onChangeEmail: {}
    )
}

#Preview("Confirming") {
    let auth = PreviewAuthService(isAuthenticated: true)
    auth.verifyDelaySeconds = 86400 // hold the spinner indefinitely for the snapshot
    return EmailVerificationView(
        email: "readyriley@sevino.ai",
        authService: auth,
        clock: PreviewClock(),
        onVerified: {},
        onChangeEmail: {}
    )
}

#Preview("Error: invalid code") {
    let auth = PreviewAuthService(isAuthenticated: true)
    let response = HTTPURLResponse(
        url: URL(string: "https://example.invalid")!,
        statusCode: 400,
        httpVersion: nil,
        headerFields: nil
    )!
    auth.verifyError = AuthError.api(
        message: "Invalid token",
        errorCode: .otpExpired,
        underlyingData: Data(),
        underlyingResponse: response
    )
    return EmailVerificationView(
        email: "readyriley@sevino.ai",
        authService: auth,
        clock: PreviewClock(),
        onVerified: {},
        onChangeEmail: {}
    )
}

#endif
