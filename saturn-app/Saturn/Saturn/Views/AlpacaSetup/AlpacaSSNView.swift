import SwiftUI

struct AlpacaSSNView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: (String) -> Void

    @State private var ssn = ""
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var typed2 = ""
    @State private var showInput = false

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
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 16 * scale)

            Spacer()

            if showInput {
                chatInput
                    .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showInput)
        .task { await animateIn() }
    }


    private var chatInput: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            TextField(
                "",
                text: $ssn,
                prompt: Text(L10n.Onboarding.alpacaSsnPlaceholder)
                    .foregroundStyle(Color.welcomeTextDimmed)
            )
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.welcomeText)
            .keyboardType(.numberPad)
            .textContentType(.none)
            .submitLabel(.send)
            .onChange(of: ssn) { _, newValue in
                ssn = formatSSN(newValue)
            }

            HStack {
                Image(systemName: "mic")
                    .font(.system(size: 18 * scale))
                    .foregroundStyle(Color.welcomeTextDimmed)
                    .accessibilityHidden(true)
                Spacer()
                Button(action: submit) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 28 * scale))
                        .foregroundStyle(isValid ? Color.welcomeText : Color.welcomeTextDimmed)
                }
                .accessibilityLabel(L10n.General.submit)
                .disabled(!isValid)
            }
        }
        .padding(14 * scale)
        .modifier(SaturnGlass.nav)
        .padding(.horizontal, 8 * scale)
        .padding(.bottom, 16 * scale)
    }

    private var isValid: Bool {
        guard digits.count == 9 else { return false }
        let area = String(digits.prefix(3))
        let group = String(digits.dropFirst(3).prefix(2))
        let serial = String(digits.suffix(4))
        if area == "000" || area == "666" || area.first == "9" { return false }
        if group == "00" { return false }
        if serial == "0000" { return false }
        return true
    }

    private var digits: String {
        ssn.filter(\.isNumber)
    }

    private func formatSSN(_ input: String) -> String {
        let d = input.filter(\.isNumber).prefix(9)
        if d.count > 5 {
            let i1 = d.index(d.startIndex, offsetBy: 3)
            let i2 = d.index(d.startIndex, offsetBy: 5)
            return "\(d[d.startIndex..<i1])-\(d[i1..<i2])-\(d[i2...])"
        } else if d.count > 3 {
            let i1 = d.index(d.startIndex, offsetBy: 3)
            return "\(d[d.startIndex..<i1])-\(d[i1...])"
        }
        return String(d)
    }

    private func submit() {
        guard isValid else { return }
        onContinue(digits)
    }


    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.alpacaSsnResponse1
            typed2 = L10n.Onboarding.alpacaSsnResponse2
            showInput = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.alpacaSsnResponse1) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(200))
        await typeOut(L10n.Onboarding.alpacaSsnResponse2) { typed2 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showInput = true }
    }

    private func typeOut(_ text: String, update: (String) -> Void) async {
        for i in 1...text.count {
            try? await Task.sleep(for: .milliseconds(25))
            update(String(text.prefix(i)))
        }
    }
}

#Preview {
    AlpacaSSNView(scale: 1, userPromptText: "Ready Riley", animate: true, onContinue: { _ in })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
