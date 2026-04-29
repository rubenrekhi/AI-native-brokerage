import MapKit
import SwiftUI

/// Popup card for editing the user's mailing address from Personal Info
/// settings. Reuses `AddressSearchCompleter` for line-1 autocomplete — picking
/// a suggestion back-fills city/state/postal the same way onboarding does.
struct EditAddressSheet: View {
    @Environment(\.popupDismiss) private var popupDismiss
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
        SevinoGlassContainer {
            popupBody
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .task(id: vm.didSave, handleDidSaveChange)
    }

    private var popupBody: some View {
        SettingsEditPopup(
            title: L10n.Settings.editAddressTitle,
            scale: scale,
            saveAction: .init(
                label: L10n.Settings.editProfileSave,
                isEnabled: canSave,
                isLoading: vm.isLoading,
                perform: save
            )
        ) {
            VStack(alignment: .leading, spacing: 12 * scale) {
                labeledField(label: L10n.Settings.editAddressLine1Label) {
                    line1Field
                }

                if showSuggestions {
                    SuggestionsList(
                        results: Array(completer.results.prefix(3)),
                        scale: scale,
                        onSelect: selectResult
                    )
                }

                labeledField(label: L10n.Settings.editAddressLine2Label) {
                    plainField(
                        text: $line2,
                        contentType: .streetAddressLine2,
                        focus: .line2,
                        submit: .next,
                        accessibilityLabel: L10n.Settings.editAddressLine2Label,
                        onSubmit: { focusedField = .city }
                    )
                }

                HStack(alignment: .top, spacing: 8 * scale) {
                    labeledField(label: L10n.Settings.editAddressCityLabel) {
                        plainField(
                            text: $city,
                            contentType: .addressCity,
                            focus: .city,
                            submit: .next,
                            accessibilityLabel: L10n.Settings.editAddressCityLabel,
                            onSubmit: { focusedField = .state }
                        )
                    }
                    labeledField(label: L10n.Settings.editAddressStateLabel) {
                        plainField(
                            text: $state,
                            contentType: .addressState,
                            focus: .state,
                            submit: .next,
                            accessibilityLabel: L10n.Settings.editAddressStateLabel,
                            onSubmit: { focusedField = .postal }
                        )
                    }
                    .frame(maxWidth: 80 * scale)
                    labeledField(label: L10n.Settings.editAddressPostalLabel) {
                        plainField(
                            text: $postalCode,
                            contentType: .postalCode,
                            focus: .postal,
                            submit: .done,
                            keyboard: .numbersAndPunctuation,
                            accessibilityLabel: L10n.Settings.editAddressPostalLabel,
                            onSubmit: { focusedField = nil }
                        )
                    }
                    .frame(maxWidth: 100 * scale)
                }
            }

            if let error = vm.error {
                Text(error)
                    .font(.system(size: 12 * scale))
                    .foregroundStyle(Color.sevinoNegative)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func labeledField<Field: View>(
        label: String,
        @ViewBuilder content: () -> Field
    ) -> some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(label)
                .font(.system(size: 11 * scale, weight: .semibold))
                .tracking(0.5)
                .textCase(.uppercase)
                .foregroundStyle(Color.sevinoGreyContrast)

            content()
        }
    }

    private var showSuggestions: Bool {
        !completer.results.isEmpty
            && line1 != committedLine1
            && !line1.isEmpty
            && focusedField == .line1
    }

    private var canSave: Bool {
        guard
            !line1.trimmingCharacters(in: .whitespaces).isEmpty,
            !city.trimmingCharacters(in: .whitespaces).isEmpty,
            !state.trimmingCharacters(in: .whitespaces).isEmpty,
            !postalCode.trimmingCharacters(in: .whitespaces).isEmpty,
            !vm.isLoading,
            !vm.didSave
        else { return false }
        return line1 != initialLine1
            || line2 != initialLine2
            || city != initialCity
            || state != initialState
            || postalCode != initialPostalCode
    }

    private var line1Field: some View {
        HStack(spacing: 8 * scale) {
            Image(systemName: "mappin.circle.fill")
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoNegative)
                .accessibilityHidden(true)

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
            .onChange(of: line1) { _, newValue in
                if newValue != committedLine1 {
                    completer.search(newValue)
                } else {
                    completer.clear()
                }
            }
            .accessibilityLabel(L10n.Settings.editAddressLine1Label)
        }
        .padding(.vertical, 10 * scale)
    }

    private func plainField(
        text: Binding<String>,
        contentType: UITextContentType,
        focus: Field,
        submit: SubmitLabel,
        keyboard: UIKeyboardType = .default,
        accessibilityLabel: String,
        onSubmit: @escaping () -> Void
    ) -> some View {
        TextField("", text: text)
            .textContentType(contentType)
            .keyboardType(keyboard)
            .autocorrectionDisabled()
            .submitLabel(submit)
            .focused($focusedField, equals: focus)
            .onSubmit(onSubmit)
            .font(.system(size: 16 * scale))
            .foregroundStyle(Color.sevinoSecondary)
            .padding(.vertical, 10 * scale)
            .accessibilityLabel(accessibilityLabel)
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
        popupDismiss()
    }
}

private struct SuggestionsList: View {
    let results: [MKLocalSearchCompletion]
    let scale: CGFloat
    let onSelect: (MKLocalSearchCompletion) -> Void

    /// Title alone isn't unique (two "123 Main St" rows can share a title in
    /// different cities). Compose with the subtitle for stable identity.
    private struct Row: Identifiable {
        let id: String
        let completion: MKLocalSearchCompletion
    }

    private var rows: [Row] {
        results.map { Row(id: "\($0.title)|\($0.subtitle)", completion: $0) }
    }

    var body: some View {
        VStack(spacing: 0) {
            ForEach(rows) { row in
                let result = row.completion
                Button {
                    onSelect(result)
                } label: {
                    HStack(spacing: 10 * scale) {
                        Image(systemName: "mappin.circle.fill")
                            .font(.system(size: 14 * scale))
                            .foregroundStyle(Color.sevinoNegative)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(result.title)
                                .font(.system(size: 13 * scale))
                                .foregroundStyle(Color.sevinoSecondary)
                                .lineLimit(1)
                            if !result.subtitle.isEmpty {
                                Text(result.subtitle)
                                    .font(.system(size: 11 * scale))
                                    .foregroundStyle(Color.sevinoGreyContrast)
                                    .lineLimit(1)
                            }
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 12 * scale)
                    .padding(.vertical, 8 * scale)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(.rect)
                }
                .buttonStyle(.plain)
            }
        }
        .modifier(SevinoGlass.popup)
    }
}

#if DEBUG
#Preview("Dark") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditAddressSheet(
                initialLine1: "123 Invest Circle",
                initialLine2: "",
                initialCity: "Cleveland",
                initialState: "OH",
                initialPostalCode: "44110",
                onSaved: {}
            )
        }
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            EditAddressSheet(
                initialLine1: "123 Invest Circle",
                initialLine2: "Apt 4B",
                initialCity: "Cleveland",
                initialState: "OH",
                initialPostalCode: "44110",
                onSaved: {}
            )
        }
        .preferredColorScheme(.light)
}
#endif
