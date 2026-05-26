import SwiftUI

struct AlpacaRegulatoryView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: (_ isSeniorOfficer: Bool, _ isAffiliatedBroker: Bool, _ isPoliticalFigure: Bool) -> Void

    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var showForm = false

    @State private var isSeniorOfficer = false
    @State private var isAffiliatedBroker = false
    @State private var isPoliticalFigure = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16 * scale) {
                    if showPrompt {
                        HStack {
                            Spacer()
                            Text(userPromptText)
                                .font(.system(size: 15 * scale))
                                .foregroundStyle(Color.welcomeText)
                                .padding(.horizontal, 16 * scale)
                                .padding(.vertical, 10 * scale)
                                .background(
                                    Color.sevinoGreyAccent.opacity(0.4),
                                    in: RoundedRectangle(cornerRadius: 16 * scale)
                                )
                        }
                        .transition(.opacity.combined(with: .offset(y: 10)))
                    }

                    if !typed1.isEmpty {
                        Text(typed1)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.welcomeText)
                    }

                    if showForm {
                        regulatoryToggles
                            .transition(.opacity.combined(with: .offset(y: 16)))
                    }
                }
                .padding(.horizontal, 20 * scale)
                .padding(.top, 16 * scale)
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)

            if showForm {
                continueButton
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showForm)
        .task { await animateIn() }
    }


    private var regulatoryToggles: some View {
        VStack(spacing: 20 * scale) {
            toggleRow(
                text: L10n.Onboarding.alpacaRegulatorySeniorOfficer,
                isOn: $isSeniorOfficer
            )
            toggleRow(
                text: L10n.Onboarding.alpacaRegulatoryBrokerAffiliated,
                isOn: $isAffiliatedBroker
            )
            toggleRow(
                text: L10n.Onboarding.alpacaRegulatoryPolitical,
                isOn: $isPoliticalFigure
            )
        }
        .padding(.top, 8 * scale)
    }

    private func toggleRow(text: String, isOn: Binding<Bool>) -> some View {
        HStack(alignment: .top, spacing: 12 * scale) {
            Text(text)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.welcomeTextSecondary)
            Spacer()
            Toggle("", isOn: isOn)
                .labelsHidden()
                .tint(.green)
        }
    }


    private var continueButton: some View {
        Button { onContinue(isSeniorOfficer, isAffiliatedBroker, isPoliticalFigure) } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(tint: Color.onboardingButtonActive))
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }


    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.alpacaRegulatoryResponse1
            showForm = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await TypewriterAnimation.typeOut(L10n.Onboarding.alpacaRegulatoryResponse1, reduceMotion: reduceMotion) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showForm = true }
    }
}

#Preview {
    AlpacaRegulatoryView(scale: 1, userPromptText: "Savings", animate: true, onContinue: { _, _, _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
