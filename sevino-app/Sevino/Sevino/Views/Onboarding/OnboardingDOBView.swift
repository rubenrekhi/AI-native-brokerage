import SwiftUI

struct OnboardingDOBView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: (String) -> Void

    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var showFields = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var month: String
    @State private var day: String
    @State private var year: String

    init(scale: CGFloat, userPromptText: String, animate: Bool, initialDOB: String = "", onContinue: @escaping (String) -> Void) {
        self.scale = scale
        self.userPromptText = userPromptText
        self.animate = animate
        self.onContinue = onContinue
        // Parse MM-DD-YYYY into components
        let parts = initialDOB.split(separator: "-")
        if parts.count == 3 {
            _month = State(initialValue: String(parts[0]))
            _day = State(initialValue: String(parts[1]))
            _year = State(initialValue: String(parts[2]))
        } else {
            _month = State(initialValue: "")
            _day = State(initialValue: "")
            _year = State(initialValue: "")
        }
    }
    @FocusState private var focused: Field?

    private enum Field: Hashable {
        case month, day, year
    }

    private var isValid: Bool {
        guard month.count == 2, day.count == 2, year.count == 4,
              let m = Int(month), let d = Int(day), let y = Int(year),
              (1...12).contains(m), (1...31).contains(d), y >= 1900, y <= Calendar.current.component(.year, from: Date.now) - 18
        else { return false }
        return true
    }

    var body: some View {
        VStack(spacing: 0) {
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
                }

                if showFields {
                    dateFields
                        .transition(.opacity.combined(with: .offset(y: 16)))
                }
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 16 * scale)

            Spacer()

            if showFields {
                continueButton
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showFields)
        .task { await animateIn() }
    }


    private var dateFields: some View {
        HStack(spacing: 16 * scale) {
            dobField(text: $month, label: L10n.Onboarding.dobMonth, field: .month)
                .frame(width: 80 * scale)
            dobField(text: $day, label: L10n.Onboarding.dobDay, field: .day)
                .frame(width: 80 * scale)
            dobField(text: $year, label: L10n.Onboarding.dobYear, field: .year)
                .frame(width: 120 * scale)
        }
        .padding(.top, 8 * scale)
        .onChange(of: month) { _, newValue in
            month = String(newValue.prefix(2))
            if month.count == 2 { focused = .day }
        }
        .onChange(of: day) { _, newValue in
            day = String(newValue.prefix(2))
            if day.count == 2 { focused = .year }
        }
        .onChange(of: year) { _, newValue in
            year = String(newValue.prefix(4))
            if year.count == 4 { focused = nil }
        }
    }

    private func dobField(text: Binding<String>, label: String, field: Field) -> some View {
        VStack(spacing: 6 * scale) {
            TextField("", text: text)
                .keyboardType(.numberPad)
                .multilineTextAlignment(.center)
                .font(.system(size: 18 * scale, weight: .medium))
                .foregroundStyle(Color.welcomeText)
                .focused($focused, equals: field)
                .padding(.horizontal, 12 * scale)
                .padding(.vertical, 14 * scale)
                .modifier(SevinoGlass.nav)

            Text(label)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.welcomeTextDimmed)
        }
    }


    private var continueButton: some View {
        Button { onContinue("\(month)-\(day)-\(year)") } label: {
            Text(L10n.Onboarding.referralContinue)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(Color.welcomeText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14 * scale)
                .contentShape(.rect(cornerRadius: CardGlass.cornerRadius))
        }
        .buttonStyle(.plain)
        .modifier(SevinoGlass.tintedButton(
            tint: isValid ? Color.onboardingButtonActive : Color.onboardingButtonInactive
        ))
        .disabled(!isValid)
        .padding(.horizontal, 32 * scale)
        .padding(.bottom, 16 * scale)
    }


    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.dobResponse1
            typed2 = L10n.Onboarding.dobResponse2
            showFields = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await TypewriterAnimation.typeOut(L10n.Onboarding.dobResponse1, reduceMotion: reduceMotion) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await TypewriterAnimation.typeOut(L10n.Onboarding.dobResponse2, reduceMotion: reduceMotion) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showFields = true }
    }
}

#Preview {
    OnboardingDOBView(
        scale: 1,
        userPromptText: "Grow my wealth over time",
        animate: true,
        onContinue: { _ in }
    )
    .background(Color.black)
    .preferredColorScheme(.dark)
}
