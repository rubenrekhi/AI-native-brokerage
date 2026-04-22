import SwiftUI

struct AlpacaAgreementsView: View {
    let scale: CGFloat
    let animate: Bool
    let onContinue: (_ agreed: Bool) -> Void

    @State private var typedHeading = ""
    @State private var showAgreements = false
    @State private var agreed = false

    private let agreements: [IdentifiableOption] = [
        L10n.Onboarding.alpacaAgreementCustomer,
        L10n.Onboarding.alpacaAgreementMargin,
        L10n.Onboarding.alpacaAgreementFdic,
    ].asIdentifiableOptions

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 20 * scale) {
                    if !typedHeading.isEmpty {
                        Text(typedHeading)
                            .font(.system(size: 20 * scale, weight: .light))
                            .foregroundStyle(Color.welcomeText)
                    }

                    if showAgreements {
                        agreementLinks
                            .transition(.opacity.combined(with: .offset(y: 16)))
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20 * scale)
                .padding(.top, 20 * scale)
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)

            if showAgreements {
                checkboxRow
                    .padding(.horizontal, 20 * scale)
                    .padding(.bottom, 12 * scale)
                openAccountButton
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showAgreements)
        .animation(.easeOut(duration: 0.2), value: agreed)
        .task { await animateIn() }
    }


    private var agreementLinks: some View {
        VStack(spacing: 12 * scale) {
            ForEach(agreements) { agreement in
                HStack {
                    Text(agreement.value)
                        .font(.system(size: 15 * scale))
                        .foregroundStyle(Color.welcomeText)
                    Spacer()
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 16 * scale))
                        .foregroundStyle(Color.welcomeTextMuted)
                        .accessibilityHidden(true)
                }
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 14 * scale)
                .modifier(SevinoGlass.nav)
            }
        }
    }


    private var checkboxRow: some View {
        Button {
            agreed.toggle()
        } label: {
            HStack(alignment: .top, spacing: 12 * scale) {
                Image(systemName: agreed ? "checkmark.square.fill" : "square")
                    .font(.system(size: 20 * scale))
                    .foregroundStyle(agreed ? Color.onboardingButtonActive : Color.welcomeTextDimmed)
                Text(L10n.Onboarding.alpacaAgreementsCheckbox)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.welcomeTextSecondary)
                    .multilineTextAlignment(.leading)
            }
        }
        .buttonStyle(.plain)
        .padding(.top, 8 * scale)
    }


    private var openAccountButton: some View {
        Button { onContinue(agreed) } label: {
            Text(L10n.Onboarding.alpacaOpenAccount)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(
            tint: agreed ? Color.onboardingButtonActive : Color.onboardingButtonInactive
        ))
        .disabled(!agreed)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }


    private func animateIn() async {
        guard animate else {
            typedHeading = L10n.Onboarding.alpacaAgreementsHeading
            showAgreements = true
            return
        }
        try? await Task.sleep(for: .milliseconds(400))
        await typeOut(L10n.Onboarding.alpacaAgreementsHeading) { typedHeading = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showAgreements = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    AlpacaAgreementsView(scale: 1, animate: true, onContinue: { _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
