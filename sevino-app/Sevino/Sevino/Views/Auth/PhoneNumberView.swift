import SwiftUI

struct PhoneNumberView: View {
    @State private var phoneVM = PhoneNumberViewModel()
    @State private var rawInput = ""
    @State private var scale: CGFloat = 1

    let onComplete: (_ phoneNumber: String) -> Void

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                Image("logo_white")
                    .resizable()
                    .scaledToFit()
                    .frame(height: 36 * scale)
                    .accessibilityLabel(L10n.General.appName)
                    .padding(.top, 8 * scale)

                ScrollView {
                    VStack(spacing: 0) {
                        PhoneTitleView(scale: scale)
                        phoneSection
                        nextButton
                    }
                }
                .scrollIndicators(.hidden)

                Spacer(minLength: 0)
            }
        }
        .background { AuthBackgroundView() }
        .preferredColorScheme(.dark)
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    scale = geo.size.width / 393
                }
            }
        }
    }

    // MARK: - Phone Input

    private var phoneSection: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(L10n.Auth.phoneLabel)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)

            HStack(spacing: 12 * scale) {
                Text(L10n.Auth.phoneCountryCode)
                    .font(.system(size: 16 * scale, weight: .medium))
                    .foregroundStyle(Color.welcomeText)
                    .padding(.horizontal, 14 * scale)
                    .padding(.vertical, 14 * scale)
                    .modifier(SevinoGlass.card)

                TextField(L10n.Auth.phonePlaceholder, text: $rawInput)
                    .keyboardType(.numberPad)
                    .textContentType(.telephoneNumber)
                    .font(.system(size: 16 * scale))
                    .foregroundStyle(Color.welcomeText)
                    .padding(.horizontal, 16 * scale)
                    .padding(.vertical, 14 * scale)
                    .modifier(SevinoGlass.card)
                    .onChange(of: rawInput) { _, newValue in
                        phoneVM.updatePhoneNumber(newValue)
                        rawInput = phoneVM.phoneNumber
                    }
            }
        }
        .padding(.top, 24 * scale)
        .padding(.horizontal, 32 * scale)
    }

    // MARK: - Next Button

    private var nextButton: some View {
        Button { onComplete(phoneVM.phoneNumber) } label: {
            Text(L10n.Auth.phoneNext)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeButtonDarkTint)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(tint: Color.welcomeButtonLightTint.opacity(0.4)))
        .disabled(!phoneVM.isPhoneValid)
        .opacity(phoneVM.isPhoneValid ? 1 : 0.6)
        .padding(.top, 20 * scale)
        .padding(.horizontal, 32 * scale)
    }
}

// MARK: - Phone Title

private struct PhoneTitleView: View {
    let scale: CGFloat

    var body: some View {
        VStack(spacing: 12 * scale) {
            Text(L10n.Auth.phoneTitle)
                .font(.dmSerif(size: 34 * scale))
                .foregroundStyle(Color.welcomeText)
                .multilineTextAlignment(.center)

            Text(L10n.Auth.phoneSubtitle)
                .font(.system(size: 15 * scale))
                .foregroundStyle(Color.welcomeText)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 24 * scale)
        .padding(.horizontal, 24 * scale)
    }
}

#Preview {
    PhoneNumberView(onComplete: { _ in })
}
