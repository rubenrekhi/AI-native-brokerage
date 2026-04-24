import SwiftUI

struct PersonalInfoSettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @Environment(\.textSizeMultiplier) private var textMultiplier

    let vm: SettingsViewModel

    @State private var baseScale: CGFloat = 1
    @State private var activeSheet: ActiveSheet?

    private enum ActiveSheet: Identifiable {
        case name
        case phone
        case address
        var id: Self { self }
    }

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                header
                    .padding(.bottom, 24 * scale)

                if vm.profile != nil {
                    content
                } else if vm.error != nil {
                    errorState
                } else {
                    loadingState
                }
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .background {
            GeometryReader { geo in
                Color.clear.onAppear {
                    baseScale = geo.size.width / 393
                }
            }
        }
        .navigationBarBackButtonHidden()
        .task {
            if vm.profile == nil {
                await vm.load()
            }
        }
        .sheet(item: $activeSheet) { sheet in
            editProfileSheet(for: sheet)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationBackground(.clear)
        }
    }

    @ViewBuilder
    private func editProfileSheet(for sheet: ActiveSheet) -> some View {
        switch sheet {
        case .name:
            EditNameSheet(
                currentFirstName: vm.profile?.profile.firstName,
                currentMiddleName: vm.profile?.profile.middleName,
                currentLastName: vm.profile?.profile.lastName,
                onSaved: { Task { await vm.reload() } }
            )
        case .phone:
            EditPhoneSheet(
                currentPhone: vm.profile?.profile.phoneNumber,
                onSaved: { Task { await vm.reload() } }
            )
        case .address:
            EditAddressSheet(
                initialLine1: currentLine1,
                initialLine2: currentLine2,
                initialCity: vm.profile?.profile.city ?? "",
                initialState: vm.profile?.profile.state ?? "",
                initialPostalCode: vm.profile?.profile.postalCode ?? "",
                onSaved: { Task { await vm.reload() } }
            )
        }
    }

    /// First non-empty street line — the backend stores the wire shape as a
    /// list so an empty leading line is possible for legacy rows.
    private var currentLine1: String {
        let lines = vm.profile?.profile.streetAddress ?? []
        return lines.first { !$0.trimmingCharacters(in: .whitespaces).isEmpty } ?? ""
    }

    /// Second line if the stored address was saved as two parts; empty
    /// otherwise. We pick the second entry (not "the line after line1") so an
    /// inadvertent leading blank doesn't shift a real apt/suite into line 1.
    private var currentLine2: String {
        let lines = vm.profile?.profile.streetAddress ?? []
        guard lines.count >= 2 else { return "" }
        return lines[1]
    }

    private var header: some View {
        SettingsHeaderView(title: L10n.Settings.personalInfo, scale: scale, onBack: { dismiss() })
    }

    private var loadingState: some View {
        ProgressView()
            .tint(Color.sevinoSecondary)
            .frame(maxWidth: .infinity)
            .padding(.top, 60 * scale)
            .accessibilityLabel(L10n.Settings.loadingPersonalInfo)
    }

    private var errorState: some View {
        ContentUnavailableView {
            Label(L10n.Settings.loadErrorTitle, systemImage: "exclamationmark.triangle")
        } description: {
            Text(L10n.Settings.loadErrorMessage)
        } actions: {
            Button(L10n.Settings.loadErrorRetry) {
                Task { await vm.reload() }
            }
            .font(.system(size: 14 * scale, weight: .medium))
            .foregroundStyle(Color.sevinoSecondary)
            .padding(.horizontal, 20 * scale)
            .padding(.vertical, 10 * scale)
            .modifier(SevinoGlass.tintedButton(tint: Color.sevinoAccent, cornerRadius: 20 * scale))
        }
        .padding(.top, 40 * scale)
    }

    private var content: some View {
        VStack(spacing: 0) {
            profileCard
                .padding(.bottom, 24 * scale)

            VStack(spacing: 0) {
                infoRow(title: L10n.Settings.nameDetails, isEnabled: true) { activeSheet = .name }
                infoRowWithValue(title: L10n.Settings.emailLabel, value: vm.displayEmail)
                infoRowWithValue(
                    title: L10n.Settings.phoneLabel,
                    value: vm.displayPhone,
                    isEnabled: true
                ) { activeSheet = .phone }
                infoRowWithValue(
                    title: L10n.Settings.mailingAddress,
                    value: vm.displayAddress,
                    isEnabled: true
                ) { activeSheet = .address }
                infoRowWithValue(title: L10n.Settings.riskTolerance, value: vm.displayRiskTolerance)
            }
        }
    }

    private var profileCard: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            HStack(spacing: 12 * scale) {
                Text(vm.displayInitials)
                    .font(.system(size: 18 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoPrimary)
                    .frame(width: 48 * scale, height: 48 * scale)
                    .background(
                        LinearGradient(
                            colors: [Color.sevinoAvatarPurple, Color.sevinoInfo],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        in: .circle
                    )

                VStack(alignment: .leading, spacing: 4 * scale) {
                    Text(vm.displayName)
                        .font(.system(size: 16 * scale, weight: .bold))
                        .foregroundStyle(Color.sevinoSecondary)

                    Text(vm.displayTier)
                        .font(.system(size: 11 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoWarning)
                        .padding(.horizontal, 8 * scale)
                        .padding(.vertical, 3 * scale)
                        .background(Color.sevinoWarning.opacity(0.15), in: .rect(cornerRadius: 4 * scale))
                }
            }

            if let duration = vm.displayMemberDuration {
                Text(L10n.Settings.usingSevino(duration))
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoGreyContrast)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16 * scale)
        .modifier(SevinoGlass.card)
    }

    private func infoRow(
        title: String,
        isEnabled: Bool = false,
        action: @escaping () -> Void = {}
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 0) {
                HStack {
                    Text(title)
                        .font(.system(size: 15 * scale))
                        .foregroundStyle(Color.sevinoSecondary)

                    Spacer()

                    Image(systemName: "pencil.line")
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.vertical, 16 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
        .disabled(!isEnabled)
    }

    private func infoRowWithValue(
        title: String,
        value: String,
        isEnabled: Bool = false,
        action: @escaping () -> Void = {}
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 0) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4 * scale) {
                        Text(title)
                            .font(.system(size: 15 * scale, weight: .medium))
                            .foregroundStyle(Color.sevinoSecondary)

                        Text(value)
                            .font(.system(size: 13 * scale))
                            .foregroundStyle(Color.sevinoGreyContrast)
                    }

                    Spacer()

                    Image(systemName: "pencil.line")
                        .font(.system(size: 15 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .accessibilityHidden(true)
                }
                .padding(.vertical, 16 * scale)

                Divider()
                    .foregroundStyle(Color.sevinoGreyAccent.opacity(0.3))
            }
        }
        .disabled(!isEnabled)
    }
}

// MARK: - Previews

#if DEBUG
#Preview("Loaded") {
    NavigationStack {
        PersonalInfoSettingsView(vm: .previewLoaded())
    }
    .preferredColorScheme(.dark)
}

#Preview("Loading") {
    NavigationStack {
        PersonalInfoSettingsView(vm: SettingsViewModel(
            settingsService: PreviewStallingSettingsService(),
            fundingService: PreviewNoopFundingService()
        ))
    }
    .preferredColorScheme(.dark)
}

#Preview("Error") {
    NavigationStack {
        PersonalInfoSettingsView(vm: .previewError())
    }
    .preferredColorScheme(.dark)
}

private extension SettingsViewModel {
    /// Returns a VM whose `profile` is populated synchronously so the preview
    /// renders the loaded state on first paint (no flash of the loading
    /// spinner).
    static func previewLoaded() -> SettingsViewModel {
        let vm = SettingsViewModel(
            settingsService: PreviewLoadedSettingsService(),
            fundingService: PreviewNoopFundingService()
        )
        vm.seedProfileForPreview(PreviewLoadedSettingsService.decodedProfile())
        return vm
    }

    static func previewError() -> SettingsViewModel {
        let vm = SettingsViewModel(
            settingsService: PreviewFailingSettingsService(),
            fundingService: PreviewNoopFundingService()
        )
        vm.seedErrorForPreview("Preview error")
        return vm
    }
}
#endif
