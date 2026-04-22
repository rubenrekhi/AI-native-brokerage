import SwiftUI

struct AlpacaEmploymentView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: (_ status: String, _ employerName: String, _ jobTitle: String) -> Void

    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var showForm = false

    @State private var employmentStatus: String
    @State private var showDropdown = false
    @State private var employerName: String
    @State private var jobTitle: String
    @State private var industry = ""

    init(
        scale: CGFloat,
        userPromptText: String,
        animate: Bool,
        initialStatus: String = "",
        initialEmployer: String = "",
        initialJobTitle: String = "",
        onContinue: @escaping (_ status: String, _ employerName: String, _ jobTitle: String) -> Void
    ) {
        self.scale = scale
        self.userPromptText = userPromptText
        self.animate = animate
        self.onContinue = onContinue
        _employmentStatus = State(initialValue: initialStatus)
        _employerName = State(initialValue: initialEmployer)
        _jobTitle = State(initialValue: initialJobTitle)
    }

    private let statuses: [IdentifiableOption] = [
        L10n.Onboarding.alpacaStatusEmployed,
        L10n.Onboarding.alpacaStatusSelfEmployed,
        L10n.Onboarding.alpacaStatusUnemployed,
        L10n.Onboarding.alpacaStatusStudent,
        L10n.Onboarding.alpacaStatusRetired,
    ].asIdentifiableOptions

    private var showEmployerFields: Bool {
        employmentStatus == L10n.Onboarding.alpacaStatusEmployed
    }

    private var isValid: Bool {
        guard !employmentStatus.isEmpty else { return false }
        if showEmployerFields {
            return !employerName.trimmingCharacters(in: .whitespaces).isEmpty
                && !jobTitle.trimmingCharacters(in: .whitespaces).isEmpty
        }
        return true
    }

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
                    }

                    if showForm {
                        formFields
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
        .animation(.easeOut(duration: 0.3), value: showEmployerFields)
        .task { await animateIn() }
    }


    private var formFields: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            VStack(alignment: .leading, spacing: 8 * scale) {
                Text(L10n.Onboarding.alpacaEmploymentStatusLabel)
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.welcomeTextSecondary)

                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showDropdown.toggle()
                    }
                } label: {
                    HStack {
                        Text(employmentStatus.isEmpty
                            ? L10n.Onboarding.alpacaEmploymentSelectPlaceholder
                            : employmentStatus)
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(employmentStatus.isEmpty
                                ? Color.welcomeTextDimmed
                                : Color.welcomeText)
                        Spacer()
                        Image(systemName: showDropdown ? "chevron.up" : "chevron.down")
                            .font(.system(size: 14 * scale))
                            .foregroundStyle(Color.welcomeTextDimmed)
                    }
                    .padding(.horizontal, 14 * scale)
                    .padding(.vertical, 14 * scale)
                    .modifier(SevinoGlass.nav)
                }
                .buttonStyle(.plain)

                if showDropdown {
                    VStack(spacing: 0) {
                        ForEach(statuses) { status in
                            Button {
                                withAnimation(.easeInOut(duration: 0.2)) {
                                    employmentStatus = status.value
                                    showDropdown = false
                                }
                            } label: {
                                Text(status.value)
                                    .font(.system(size: 16 * scale))
                                    .foregroundStyle(Color.welcomeText)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.horizontal, 14 * scale)
                                    .padding(.vertical, 12 * scale)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .modifier(SevinoGlass.nav)
                    .transition(.opacity.combined(with: .offset(y: -8)))
                }
            }

            if showEmployerFields {
                VStack(alignment: .leading, spacing: 16 * scale) {
                    formTextField(
                        label: L10n.Onboarding.alpacaEmployerNameLabel,
                        placeholder: L10n.Onboarding.alpacaEmployerNamePlaceholder,
                        text: $employerName
                    )
                    formTextField(
                        label: L10n.Onboarding.alpacaJobTitleLabel,
                        placeholder: L10n.Onboarding.alpacaJobTitlePlaceholder,
                        text: $jobTitle
                    )
                    formTextField(
                        label: L10n.Onboarding.alpacaIndustryLabel,
                        placeholder: L10n.Onboarding.alpacaIndustryPlaceholder,
                        text: $industry,
                        optional: true
                    )
                }
                .transition(.opacity.combined(with: .offset(y: 8)))
            }
        }
    }

    private func formTextField(
        label: String,
        placeholder: String,
        text: Binding<String>,
        optional: Bool = false
    ) -> some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            HStack(spacing: 4) {
                Text(label)
                    .font(.system(size: 14 * scale))
                    .foregroundStyle(Color.welcomeTextSecondary)
                if optional {
                    Text(L10n.Onboarding.alpacaOptionalLabel)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.welcomeTextDimmed)
                }
            }

            TextField(
                "",
                text: text,
                prompt: Text(placeholder).foregroundStyle(Color.welcomeTextDimmed)
            )
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.welcomeText)
            .textInputAutocapitalization(.words)
            .padding(.horizontal, 14 * scale)
            .padding(.vertical, 14 * scale)
            .modifier(SevinoGlass.nav)
        }
    }


    private var continueButton: some View {
        Button { onContinue(employmentStatus, employerName, jobTitle) } label: {
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
            typed1 = L10n.Onboarding.alpacaEmploymentResponse1
            typed2 = L10n.Onboarding.alpacaEmploymentResponse2
            showForm = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.alpacaEmploymentResponse1) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaEmploymentResponse2) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showForm = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    AlpacaEmploymentView(scale: 1, userPromptText: "Yes, US citizen", animate: true) { _, _, _ in }
        .background(Color.black)
        .preferredColorScheme(.dark)
}
