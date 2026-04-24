import MapKit
import SwiftUI

/// Sheet for editing the user's mailing address from Personal Info settings.
/// Reuses `AddressSearchCompleter` for line-1 autocomplete — picking a
/// suggestion back-fills city/state/postal the same way onboarding does.
struct EditAddressSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    let initialLine1: String
    let initialLine2: String
    let initialCity: String
    let initialState: String
    let initialPostalCode: String
    let onSaved: () -> Void

    @State private var vm: EditProfileViewModel
    @State private var line1: String
    @State private var line2: String
    @State private var city: String
    @State private var state: String
    @State private var postalCode: String

    /// The last text the user explicitly accepted for line 1 (either the
    /// initial value or a tapped autocomplete result). We hide suggestions as
    /// long as `line1` matches this — that way the list reappears only when
    /// the user starts editing again.
    @State private var committedLine1: String
    @State private var completer = AddressSearchCompleter()
    @State private var baseScale: CGFloat = 1
    @FocusState private var focusedField: Field?

    private var scale: CGFloat { baseScale * textMultiplier }

    init(
        initialLine1: String,
        initialLine2: String,
        initialCity: String,
        initialState: String,
        initialPostalCode: String,
        vm: EditProfileViewModel = EditProfileViewModel(),
        onSaved: @escaping () -> Void = {}
    ) {
        self.initialLine1 = initialLine1
        self.initialLine2 = initialLine2
        self.initialCity = initialCity
        self.initialState = initialState
        self.initialPostalCode = initialPostalCode
        self.onSaved = onSaved
        _vm = State(initialValue: vm)
        _line1 = State(initialValue: initialLine1)
        _line2 = State(initialValue: initialLine2)
        _city = State(initialValue: initialCity)
        _state = State(initialValue: initialState)
        _postalCode = State(initialValue: initialPostalCode)
        _committedLine1 = State(initialValue: initialLine1)
    }

    enum Field: Hashable { case line1, line2, city, state, postal }

    var body: some View {
        NavigationStack {
            ScrollView {
                SevinoGlassContainer {
                    formContent
                }
                .padding(.horizontal, 20 * scale)
                .padding(.top, 12 * scale)
                .padding(.bottom, 24 * scale)
            }
            .scrollDismissesKeyboard(.interactively)
            .background {
                Color.sevinoSettingsBg
                    .ignoresSafeArea()
            }
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.width
            } action: { width in
                baseScale = width / 393
            }
            .navigationTitle(L10n.Settings.editAddressTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.Settings.editProfileCancel) { dismiss() }
                        .foregroundStyle(Color.sevinoSecondary)
                        .disabled(vm.isLoading)
                }
            }
            .overlay(alignment: .top) {
                if vm.didSave {
                    SuccessBanner(scale: scale)
                        .padding(.top, 8 * scale)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .animation(.easeInOut(duration: 0.25), value: vm.didSave)
            .task(id: vm.didSave, handleDidSaveChange)
        }
    }

    private var formContent: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            line1Field

            if showSuggestions {
                SuggestionsList(
                    results: Array(completer.results.prefix(5)),
                    scale: scale,
                    onSelect: selectResult
                )
            }

            labeledField(
                label: L10n.Settings.editAddressLine2Label,
                text: $line2,
                contentType: .streetAddressLine2,
                focus: .line2,
                submit: .next,
                onSubmit: { focusedField = .city }
            )

            HStack(spacing: 12 * scale) {
                labeledField(
                    label: L10n.Settings.editAddressCityLabel,
                    text: $city,
                    contentType: .addressCity,
                    focus: .city,
                    submit: .next,
                    onSubmit: { focusedField = .state }
                )
                labeledField(
                    label: L10n.Settings.editAddressStateLabel,
                    text: $state,
                    contentType: .addressState,
                    focus: .state,
                    submit: .next,
                    onSubmit: { focusedField = .postal }
                )
                .frame(maxWidth: 100 * scale)
            }

            labeledField(
                label: L10n.Settings.editAddressPostalLabel,
                text: $postalCode,
                contentType: .postalCode,
                focus: .postal,
                submit: .done,
                keyboard: .numbersAndPunctuation,
                onSubmit: { focusedField = nil }
            )

            if let error = vm.error {
                Text(error)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoNegative)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            saveButton
                .padding(.top, 8 * scale)
        }
    }

    private var showSuggestions: Bool {
        !completer.results.isEmpty
            && line1 != committedLine1
            && !line1.isEmpty
    }

    private var canSave: Bool {
        !line1.trimmingCharacters(in: .whitespaces).isEmpty &&
        !city.trimmingCharacters(in: .whitespaces).isEmpty &&
        !state.trimmingCharacters(in: .whitespaces).isEmpty &&
        !postalCode.trimmingCharacters(in: .whitespaces).isEmpty &&
        !vm.isLoading &&
        !vm.didSave
    }

    private var line1Field: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(L10n.Settings.editAddressLine1Label)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            TextField(
                "",
                text: $line1,
                prompt: Text(L10n.Settings.editAddressLine1Placeholder)
                    .foregroundStyle(Color.welcomeTextDimmed)
            )
            .textContentType(.streetAddressLine1)
            .autocorrectionDisabled()
            .submitLabel(.next)
            .focused($focusedField, equals: .line1)
            .onSubmit { focusedField = .line2 }
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.sevinoSecondary)
            .padding(.horizontal, 16 * scale)
            .padding(.vertical, 14 * scale)
            .modifier(SevinoGlass.card)
            .onChange(of: line1) { _, newValue in
                if newValue != committedLine1 {
                    completer.search(newValue)
                } else {
                    completer.clear()
                }
            }
            .accessibilityLabel(L10n.Settings.editAddressLine1Label)
        }
    }

    private func labeledField(
        label: String,
        text: Binding<String>,
        contentType: UITextContentType,
        focus: Field,
        submit: SubmitLabel,
        keyboard: UIKeyboardType = .default,
        onSubmit: @escaping () -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(label)
                .font(.system(size: 13 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)

            TextField("", text: text)
                .textContentType(contentType)
                .keyboardType(keyboard)
                .autocorrectionDisabled()
                .submitLabel(submit)
                .focused($focusedField, equals: focus)
                .onSubmit(onSubmit)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .padding(.horizontal, 16 * scale)
                .padding(.vertical, 14 * scale)
                .modifier(SevinoGlass.card)
                .accessibilityLabel(label)
        }
    }

    private var saveButton: some View {
        Button(action: save) {
            Group {
                if vm.isLoading {
                    ProgressView()
                        .tint(Color.sevinoSecondary)
                } else {
                    Text(L10n.Settings.editProfileSave)
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14 * scale)
            .contentShape(.rect(cornerRadius: 14 * scale))
        }
        .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 14 * scale))
        .disabled(!canSave)
        .opacity(canSave ? 1 : 0.6)
    }

    private func selectResult(_ result: MKLocalSearchCompletion) {
        focusedField = nil
        completer.clear()
        // Optimistically accept the title as line 1 so the list hides
        // immediately; geocoding then refines the parts.
        let immediateLine1 = result.title
        line1 = immediateLine1
        committedLine1 = immediateLine1

        Task {
            guard let resolved = await vm.resolveCompletion(result) else { return }
            if let street = resolved.streetLine1 {
                line1 = street
                committedLine1 = street
            }
            if let resolvedCity = resolved.city { city = resolvedCity }
            if let resolvedState = resolved.state { state = resolvedState }
            if let resolvedPostal = resolved.postalCode { postalCode = resolvedPostal }
        }
    }

    private func save() {
        focusedField = nil
        let trimmedLine2 = line2.trimmingCharacters(in: .whitespacesAndNewlines)
        var street = [line1]
        if !trimmedLine2.isEmpty {
            street.append(trimmedLine2)
        }
        Task {
            await vm.saveAddress(
                street: street,
                city: city,
                state: state,
                postalCode: postalCode
            )
        }
    }

    private func handleDidSaveChange() async {
        guard vm.didSave else { return }
        onSaved()
        try? await Task.sleep(for: .milliseconds(900))
        guard !Task.isCancelled else { return }
        dismiss()
    }
}

private struct SuggestionsList: View {
    let results: [MKLocalSearchCompletion]
    let scale: CGFloat
    let onSelect: (MKLocalSearchCompletion) -> Void

    var body: some View {
        VStack(spacing: 0) {
            ForEach(results, id: \.self) { result in
                Button {
                    onSelect(result)
                } label: {
                    HStack(spacing: 12 * scale) {
                        Image(systemName: "mappin.circle.fill")
                            .font(.system(size: 16 * scale))
                            .foregroundStyle(Color.sevinoNegative)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(result.title)
                                .font(.system(size: 14 * scale))
                                .foregroundStyle(Color.sevinoSecondary)
                                .lineLimit(1)
                            if !result.subtitle.isEmpty {
                                Text(result.subtitle)
                                    .font(.system(size: 12 * scale))
                                    .foregroundStyle(Color.sevinoGreyContrast)
                                    .lineLimit(1)
                            }
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 14 * scale)
                    .padding(.vertical, 10 * scale)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
            }
        }
        .modifier(SevinoGlass.nav)
    }
}

private struct SuccessBanner: View {
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.sevinoPositive)
            Text(L10n.Settings.editProfileSuccess)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(Color.sevinoSecondary)
        }
        .padding(.horizontal, 16 * scale)
        .padding(.vertical, 10 * scale)
        .modifier(SevinoGlass.popup)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isStaticText)
    }
}

#if DEBUG
#Preview("Dark") {
    EditAddressSheet(
        initialLine1: "123 Invest Circle",
        initialLine2: "",
        initialCity: "Cleveland",
        initialState: "OH",
        initialPostalCode: "44110",
        onSaved: {}
    )
    .preferredColorScheme(.dark)
}

#Preview("Light") {
    EditAddressSheet(
        initialLine1: "123 Invest Circle",
        initialLine2: "Apt 4B",
        initialCity: "Cleveland",
        initialState: "OH",
        initialPostalCode: "44110",
        onSaved: {}
    )
    .preferredColorScheme(.light)
}
#endif
