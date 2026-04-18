import SwiftUI

struct OnboardingSingleSelectView: View {
    let scale: CGFloat
    let userPromptText: String
    let response1: String
    let response2: String
    var response3: String = ""
    let options: [String]
    let animate: Bool
    let initialSelected: String?
    let onContinue: (String) -> Void

    @State private var selected: String?

    init(
        scale: CGFloat,
        userPromptText: String,
        response1: String,
        response2: String,
        response3: String = "",
        options: [String],
        animate: Bool,
        initialSelected: String? = nil,
        onContinue: @escaping (String) -> Void
    ) {
        self.scale = scale
        self.userPromptText = userPromptText
        self.response1 = response1
        self.response2 = response2
        self.response3 = response3
        self.options = options
        self.animate = animate
        self.initialSelected = initialSelected
        self.onContinue = onContinue
        _selected = State(initialValue: initialSelected)
    }
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var typed3 = ""
    @State private var showOptions = false

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
                        if !typed3.isEmpty {
                            Text(typed3)
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
                        selected = option
                    }
                } label: {
                    Text(option)
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.welcomeText)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14 * scale)
                        .padding(.horizontal, 16 * scale)
                        .modifier(SevinoGlass.tintedButton(
                            tint: selected == option
                                ? Color.sevinoAccent
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
        Button { onContinue(selected ?? "") } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(
            tint: selected != nil ? Color.onboardingButtonActive : Color.onboardingButtonInactive
        ))
        .disabled(selected == nil)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }


    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = response1
            typed2 = response2
            typed3 = response3
            showOptions = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(response1) { typed1 = $0 }
        if !response2.isEmpty {
            try? await Task.sleep(for: .milliseconds(200))
            await typeOut(response2) { typed2 = $0 }
        }
        if !response3.isEmpty {
            try? await Task.sleep(for: .milliseconds(200))
            await typeOut(response3) { typed3 = $0 }
        }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showOptions = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        guard !text.isEmpty else { return }
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    OnboardingSingleSelectView(
        scale: 1,
        userPromptText: "01-08-2004",
        response1: "What's your annual income, before taxes?",
        response2: "I use this to tailor guidance to your situation. No judgment — every number is a great starting point.",
        options: ["Under $25K", "$25K – $50K", "$50K – $100K", "$100K – $200K", "$200K – $500K", "$500K+"],
        animate: true,
        onContinue: { _ in }
    )
    .background(Color.black)
    .preferredColorScheme(.dark)
}
