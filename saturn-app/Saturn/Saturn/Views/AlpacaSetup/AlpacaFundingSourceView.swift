import SwiftUI

struct AlpacaFundingSourceView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: (_ sources: Set<String>) -> Void

    @State private var selected: Set<String> = []
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var showOptions = false

    private let options = [
        L10n.Onboarding.alpacaFundingEmployment,
        L10n.Onboarding.alpacaFundingSavings,
        L10n.Onboarding.alpacaFundingInvestments,
        L10n.Onboarding.alpacaFundingBusiness,
        L10n.Onboarding.alpacaFundingFamily,
        L10n.Onboarding.alpacaFundingInheritance,
    ]

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
                                    Color.saturnGreyAccent.opacity(0.4),
                                    in: RoundedRectangle(cornerRadius: 16 * scale)
                                )
                        }
                        .transition(.opacity.combined(with: .offset(y: 10)))
                    }

                    VStack(alignment: .leading, spacing: 12 * scale) {
                        if !typed1.isEmpty {
                            Text(typed1)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.welcomeText)
                        }
                        if !typed2.isEmpty {
                            Text(typed2)
                                .font(.system(size: 16 * scale))
                                .foregroundStyle(Color.welcomeText)
                        }
                    }

                    if showOptions {
                        optionsList
                            .transition(.opacity.combined(with: .offset(y: 16)))
                    }
                }
                .padding(.horizontal, 20 * scale)
                .padding(.top, 16 * scale)
                .padding(.bottom, 16 * scale)
            }
            .scrollIndicators(.hidden)

            if showOptions {
                continueButton
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showOptions)
        .task { await animateIn() }
    }

    private var optionsList: some View {
        VStack(spacing: 12 * scale) {
            ForEach(options, id: \.self) { option in
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        if selected.contains(option) {
                            selected.remove(option)
                        } else {
                            selected.insert(option)
                        }
                    }
                } label: {
                    Text(option)
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                        .padding(.horizontal, 16 * scale)
                        .modifier(SaturnGlass.tintedButton(
                            tint: selected.contains(option)
                                ? Color.saturnAccent
                                : Color.clear,
                            cornerRadius: 16
                        ))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.top, 8 * scale)
    }

    private var continueButton: some View {
        Button { onContinue(selected) } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SaturnGlass.tintedButton(
            tint: selected.isEmpty ? Color.onboardingButtonInactive : Color.onboardingButtonActive
        ))
        .disabled(selected.isEmpty)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }

    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.alpacaFundingResponse1
            typed2 = L10n.Onboarding.alpacaFundingResponse2
            showOptions = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.alpacaFundingResponse1) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaFundingResponse2) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showOptions = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    AlpacaFundingSourceView(scale: 1, userPromptText: "Employed", animate: true, onContinue: { _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
