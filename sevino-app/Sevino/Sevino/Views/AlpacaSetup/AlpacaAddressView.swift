import MapKit
import SwiftUI

struct AlpacaAddressView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let onContinue: (ParsedAddress) -> Void

    @State private var query = ""
    @State private var selectedAddress = ""
    @State private var selectedCompletion: MKLocalSearchCompletion?
    @State private var showPrompt = false
    @State private var typed1 = ""
    @State private var showInput = false
    @State private var completer = AddressSearchCompleter()

    private var showSuggestions: Bool {
        !completer.results.isEmpty && selectedAddress.isEmpty && !query.isEmpty
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
                }
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 16 * scale)

            Spacer()

            if showInput {
                VStack(spacing: 0) {
                    if showSuggestions {
                        suggestionsOverlay
                    }
                    chatInput
                }
                .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showInput)
        .task { await animateIn() }
    }


    private var suggestionsOverlay: some View {
        SevinoGlassContainer {
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(completer.results.prefix(6), id: \.self) { result in
                        Button {
                            selectResult(result)
                        } label: {
                            HStack(spacing: 12 * scale) {
                                Image(systemName: "mappin.circle.fill")
                                    .font(.system(size: 18 * scale))
                                    .foregroundStyle(Color.sevinoNegative)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(result.title)
                                        .font(.system(size: 14 * scale))
                                        .foregroundStyle(Color.welcomeText)
                                        .lineLimit(1)
                                    if !result.subtitle.isEmpty {
                                        Text(result.subtitle)
                                            .font(.system(size: 12 * scale))
                                            .foregroundStyle(Color.welcomeTextDimmed)
                                            .lineLimit(1)
                                    }
                                }
                                Spacer()
                            }
                            .padding(.horizontal, 14 * scale)
                            .padding(.vertical, 10 * scale)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .frame(maxHeight: 220 * scale)
            .modifier(SevinoGlass.nav)
        }
        .padding(.horizontal, 8 * scale)
        .padding(.bottom, 4 * scale)
    }


    private var chatInput: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            TextField(
                "",
                text: $query,
                prompt: Text(L10n.Onboarding.alpacaAddressPlaceholder)
                    .foregroundStyle(Color.welcomeTextDimmed)
            )
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.welcomeText)
            .textContentType(.fullStreetAddress)
            .autocorrectionDisabled()
            .onChange(of: query) { _, newValue in
                if selectedAddress.isEmpty {
                    completer.search(newValue)
                }
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
                        .foregroundStyle(!selectedAddress.isEmpty ? Color.welcomeText : Color.welcomeTextDimmed)
                }
                .accessibilityLabel(L10n.General.submit)
                .disabled(selectedAddress.isEmpty)
            }
        }
        .padding(14 * scale)
        .modifier(SevinoGlass.nav)
        .padding(.horizontal, 8 * scale)
        .padding(.bottom, 16 * scale)
    }

    private func selectResult(_ result: MKLocalSearchCompletion) {
        let full = result.subtitle.isEmpty ? result.title : "\(result.title), \(result.subtitle)"
        selectedAddress = full
        selectedCompletion = result
        query = full
        completer.clear()
    }

    private func submit() {
        guard !selectedAddress.isEmpty, let completion = selectedCompletion else { return }
        let fallback = ParsedAddress(
            streetAddress: selectedAddress, city: "", state: "", postalCode: "", fullDisplay: selectedAddress
        )
        Task {
            let request = MKLocalSearch.Request(completion: completion)
            let search = MKLocalSearch(request: request)
            do {
                let response = try await search.start()
                guard let placemark = response.mapItems.first?.placemark else {
                    onContinue(fallback)
                    return
                }
                let street = [placemark.subThoroughfare, placemark.thoroughfare]
                    .compactMap { $0 }
                    .joined(separator: " ")
                onContinue(ParsedAddress(
                    streetAddress: street.isEmpty ? selectedAddress : street,
                    city: placemark.locality ?? "",
                    state: placemark.administrativeArea ?? "",
                    postalCode: placemark.postalCode ?? "",
                    fullDisplay: selectedAddress
                ))
            } catch {
                onContinue(fallback)
            }
        }
    }


    private func animateIn() async {
        guard animate else {
            showPrompt = true
            typed1 = L10n.Onboarding.alpacaAddressResponse1
            showInput = true
            return
        }
        try? await Task.sleep(for: .milliseconds(200))
        withAnimation(.easeOut(duration: 0.3)) { showPrompt = true }
        try? await Task.sleep(for: .milliseconds(500))
        await typeOut(L10n.Onboarding.alpacaAddressResponse1) { typed1 = $0 }
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
    AlpacaAddressView(scale: 1, userPromptText: "XXX-XX-XXXX", animate: true, onContinue: { _ in  })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
