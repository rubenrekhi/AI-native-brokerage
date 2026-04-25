import SwiftUI

/// Phone OTP entry screen.
///
/// Owns a `PhoneVerificationViewModel` for the lifetime of the view and threads
/// its state into:
/// - the `OTPInputView` (boxes auto-submit on the 6th digit through the VM)
/// - the resend pill / live-countdown caption
/// - the muted-red error line under the box row
///
/// Lifecycle:
/// 1. `.task` fires `vm.onAppear()` once on appear — sends the initial OTP and
///    starts the 30s cooldown. Re-entry from SwiftUI's `.task` is gated inside
///    the VM, so re-renders don't spam the backend.
/// 2. Local `otpInput` state is the binding the boxes read/write; we mirror it
///    to `vm.otp` via `onCodeChange` so the canonical value lives on the VM,
///    but reads stay synchronous from SwiftUI's perspective.
/// 3. On a successful confirm `vm.isVerified` flips, we call `onVerified()` —
///    the parent route advances to onboarding. On a back-tap we hand off to
///    `onChangeNumber()` so the user returns to `PhoneNumberView` with their
///    formatted number preserved.
struct PhoneVerificationView: View {
    private let onVerified: () -> Void
    private let onChangeNumber: () -> Void

    @State private var vm: PhoneVerificationViewModel
    @State private var otpInput: String = ""
    @State private var scale: CGFloat = 1
    @AccessibilityFocusState private var otpFieldFocused: Bool

    init(
        phoneNumber: String,
        service: any PhoneVerificationServiceProtocol = PhoneVerificationService.shared,
        clock: any ClockProtocol = SystemClock(),
        onVerified: @escaping () -> Void,
        onChangeNumber: @escaping () -> Void
    ) {
        self.onVerified = onVerified
        self.onChangeNumber = onChangeNumber
        _vm = State(wrappedValue: PhoneVerificationViewModel(
            phoneNumber: phoneNumber,
            service: service,
            clock: clock
        ))
    }

    var body: some View {
        ZStack {
            AuthBackgroundView()
            SevinoGlassContainer {
                VStack(spacing: 0) {
                    AuthHeaderView(scale: scale, onBack: onChangeNumber)
                    ScrollView {
                        VStack(spacing: 0) {
                            titleSection
                            otpSection
                            errorSection
                            nextButton
                            resendSection
                        }
                    }
                    .scrollIndicators(.hidden)
                    Spacer(minLength: 0)
                }
            }
        }
        .preferredColorScheme(.dark)
        .background(scaleAnchor)
        .task {
            await vm.onAppear()
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
        .sensoryFeedback(.error, trigger: vm.error)
        .sensoryFeedback(.success, trigger: vm.isVerified)
    }

    // MARK: - Sections

    private var titleSection: some View {
        Text(L10n.Auth.otpTitle(vm.phoneNumber))
            .font(.dmSerif(size: 28 * scale))
            .foregroundStyle(Color.welcomeText)
            .multilineTextAlignment(.center)
            .padding(.top, 32 * scale)
            .padding(.horizontal, 24 * scale)
    }

    private var otpSection: some View {
        OTPInputView(
            code: $otpInput,
            scale: scale,
            errorState: isOTPRejected,
            onCodeChange: { value in
                Task { await vm.updateOTP(value) }
            }
        )
        .accessibilityFocused($otpFieldFocused)
        .padding(.top, 32 * scale)
        .padding(.horizontal, 32 * scale)
    }

    @ViewBuilder
    private var errorSection: some View {
        if let message = vm.error?.errorDescription {
            Text(message)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoNegative)
                .multilineTextAlignment(.center)
                .padding(.top, 12 * scale)
                .padding(.horizontal, 24 * scale)
        }
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
            } else {
                Text(L10n.Auth.otpResendCountdown(vm.secondsRemaining))
                    .font(.system(size: 14 * scale, weight: .medium))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .frame(minHeight: 44 * scale)
            }
        }
        .padding(.top, 12 * scale)
    }

    // MARK: - Helpers

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
}

// MARK: - Previews

#if DEBUG
#Preview("Idle") {
    PhoneVerificationView(
        phoneNumber: "(555) 123-4567",
        service: PreviewVerificationService(),
        clock: PreviewClock(),
        onVerified: {},
        onChangeNumber: {}
    )
}

#Preview("Send failed") {
    PhoneVerificationView(
        phoneNumber: "(555) 123-4567",
        service: PreviewVerificationService(sendError: URLError(.notConnectedToInternet)),
        clock: PreviewClock(),
        onVerified: {},
        onChangeNumber: {}
    )
}

#Preview("Resend ready") {
    PhoneVerificationView(
        phoneNumber: "(555) 123-4567",
        service: PreviewVerificationService(),
        clock: PreviewClock(returnsImmediately: true),
        onVerified: {},
        onChangeNumber: {}
    )
}

private struct PreviewVerificationService: PhoneVerificationServiceProtocol {
    var sendError: Error?
    var confirmError: Error?

    func sendOTP(phoneNumber: String) async throws {
        if let sendError { throw sendError }
    }

    func confirmOTP(phoneNumber: String, code: String) async throws {
        if let confirmError { throw confirmError }
    }
}

private struct PreviewClock: ClockProtocol {
    var returnsImmediately: Bool = false

    func sleep(seconds: Int) async throws {
        if returnsImmediately { return }
        try await Task.sleep(for: .seconds(86400))
    }
}
#endif
