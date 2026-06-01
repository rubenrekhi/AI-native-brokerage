import MapKit
import SwiftUI

struct AlpacaAddressView: View {
    let scale: CGFloat
    let userPromptText: String
    let animate: Bool
    let initialAddress: ParsedAddress?
    let onContinue: (ParsedAddress) -> Void

    @State private var query: String
    @State private var selectedAddress: String
    @State private var selectedCompletion: MKLocalSearchCompletion?
    @State private var showPrompt: Bool
    @State private var typed1: String
    @State private var showInput: Bool
    @State private var addressError: String?
    // Root owner of this @Observable; @State is correct here. Pass to child views as a plain parameter — do not re-wrap.
    @State private var completer = AddressSearchCompleter()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(
        scale: CGFloat,
        userPromptText: String,
        animate: Bool,
        initialAddress: ParsedAddress? = nil,
        onContinue: @escaping (ParsedAddress) -> Void
    ) {
        self.scale = scale
        self.userPromptText = userPromptText
        self.animate = animate
        self.initialAddress = initialAddress
        self.onContinue = onContinue

        let display = initialAddress?.fullDisplay ?? ""
        _query = State(initialValue: display)
        _selectedAddress = State(initialValue: display)
        // When resuming with a saved address, skip the animated intro so the
        // user sees their prior selection immediately and can just tap Continue.
        let hasInitial = initialAddress != nil
        _showPrompt = State(initialValue: hasInitial)
        _typed1 = State(initialValue: hasInitial ? L10n.Onboarding.alpacaAddressResponse1 : "")
        _showInput = State(initialValue: hasInitial)
    }

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
                SevinoGlassContainer {
                    VStack(spacing: 0) {
                        if showSuggestions {
                            suggestionsOverlay
                        }
                        chatInput
                    }
                }
                .transition(.opacity.combined(with: .offset(y: 16)))
            }
        }
        .animation(.easeOut(duration: 0.3), value: showInput)
        .task { await animateIn() }
    }


    private var suggestionsOverlay: some View {
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
                // If the text drifted away from the current selection (either a
                // pre-filled resume value or a previously picked suggestion),
                // clear the selection so MapKit suggestions re-appear.
                if newValue != selectedAddress {
                    selectedAddress = ""
                    selectedCompletion = nil
                    addressError = nil
                    completer.search(newValue)
                }
            }

            if let addressError {
                Text(addressError)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoNegative)
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
        guard !selectedAddress.isEmpty else { return }
        addressError = nil

        // Resuming without changing anything — reuse the saved ParsedAddress so
        // we don't re-hit MapKit (which wouldn't be able to geocode our own
        // stored display string into a completion anyway).
        if selectedCompletion == nil,
           let initial = initialAddress,
           selectedAddress == initial.fullDisplay {
            onContinue(initial)
            return
        }

        guard let completion = selectedCompletion else { return }
        Task {
            let request = MKLocalSearch.Request(completion: completion)
            let search = MKLocalSearch(request: request)
            do {
                let response = try await search.start()
                guard let placemark = response.mapItems.first?.placemark else {
                    showAddressError(L10n.Onboarding.alpacaAddressParseError)
                    return
                }
                // Sevino is US-only; a Canadian pick resolves to e.g. "ON",
                // which Alpaca rejects. Gate on the same state set the backend
                // enforces (USStateCodes) rather than continuing.
                guard USStateCodes.isValid(placemark.administrativeArea ?? "") else {
                    showAddressError(L10n.Onboarding.alpacaAddressNonUSError)
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
                showAddressError(L10n.Onboarding.alpacaAddressParseError)
            }
        }
    }

    private func showAddressError(_ message: String) {
        addressError = message
        selectedAddress = ""
        selectedCompletion = nil
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
        await TypewriterAnimation.typeOut(L10n.Onboarding.alpacaAddressResponse1, reduceMotion: reduceMotion) { typed1 = $0 }
        try? await Task.sleep(for: .milliseconds(300))
        withAnimation(.easeOut(duration: 0.3)) { showInput = true }
    }
}

#Preview {
    AlpacaAddressView(scale: 1, userPromptText: "XXX-XX-XXXX", animate: true, onContinue: { _ in  })
        .background(Color.black)
        .preferredColorScheme(.dark)
}
