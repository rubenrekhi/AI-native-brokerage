import Foundation

@Observable
final class SettingsViewModel {
    private let settingsService: any SettingsServiceProtocol
    private let fundingService: any FundingServiceProtocol
    private let authService: any AuthServiceProtocol
    private let now: @Sendable () -> Date

    private(set) var profile: SettingsProfileResponse?
    private(set) var accountValue: AccountValueResponse?
    private(set) var cashEnrollmentState: EnrollmentState = .unavailable
    private(set) var isLoading = false
    private(set) var isDeletingAccount = false
    private(set) var isClosingBrokerage = false
    private(set) var didCloseBrokerage = false
    private(set) var error: String?
    private(set) var deleteError: String?
    private(set) var closeBrokerageError: String?

    let plaidLink: PlaidLinkCoordinator

    /// Bindable driver for the delete-account error alert. The setter discards
    /// `deleteError` when the alert dismisses; using a computed projection keeps
    /// the `.alert(isPresented:)` binding out of the view `body`.
    var showDeleteError: Bool {
        get { deleteError != nil }
        set { if !newValue { deleteError = nil } }
    }

    /// Bindable driver for the close-brokerage-account error alert. Mirrors the
    /// `showDeleteError` pattern — the setter clears the error on dismiss.
    var showCloseBrokerageError: Bool {
        get { closeBrokerageError != nil }
        set { if !newValue { closeBrokerageError = nil } }
    }

    init(
        settingsService: any SettingsServiceProtocol = SettingsService.shared,
        fundingService: any FundingServiceProtocol = FundingService.shared,
        authService: any AuthServiceProtocol = AuthService.shared,
        now: @escaping @Sendable () -> Date = { .now }
    ) {
        self.settingsService = settingsService
        self.fundingService = fundingService
        self.authService = authService
        self.now = now
        self.plaidLink = PlaidLinkCoordinator(service: fundingService)
        self.plaidLink.onLinked = { [weak self] in
            await self?.refreshProfileAfterLink()
        }
    }

    private func refreshProfileAfterLink() async {
        // Best-effort refresh — the link itself succeeded, so any failure here
        // shouldn't surface as an error to the user.
        if let refreshed = try? await settingsService.getProfile() {
            profile = refreshed
        }
    }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        async let cashState: Void = loadCashEnrollmentState()
        do {
            async let profileResult = settingsService.getProfile()
            async let accountValueResult = settingsService.getAccountValue()
            profile = try await profileResult
            accountValue = try await accountValueResult
        } catch {
            self.error = error.localizedDescription
        }
        await cashState
    }

    /// Best-effort — a failure leaves the row hidden rather than blocking the
    /// rest of the Settings screen, so it must not propagate out of `load()`.
    private func loadCashEnrollmentState() async {
        guard let cash = try? await fundingService.getCashInterest() else { return }
        cashEnrollmentState = cash.enrollmentState ?? .unavailable
    }

    func reload() async {
        await load()
    }

    func unlinkAccount(_ id: UUID) async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            try await fundingService.deleteAchRelationship(id: id)
            async let profileResult = settingsService.getProfile()
            async let accountValueResult = settingsService.getAccountValue()
            profile = try await profileResult
            accountValue = try await accountValueResult
        } catch {
            self.error = error.localizedDescription
        }
    }

    func deleteAccount() async {
        deleteError = nil
        isDeletingAccount = true
        defer { isDeletingAccount = false }
        do {
            try await settingsService.deleteAccount()
        } catch {
            self.deleteError = error.localizedDescription
            return
        }
        // Server delete succeeded — the account is gone. Best-effort sign-out
        // only; surfacing a sign-out failure here would leave the user looking
        // at an error for an account that no longer exists.
        try? await authService.signOut()
    }

    func closeBrokerageAccount() async {
        closeBrokerageError = nil
        isClosingBrokerage = true
        defer { isClosingBrokerage = false }
        do {
            try await settingsService.closeBrokerageAccount()
        } catch {
            self.closeBrokerageError = error.localizedDescription
            return
        }
        didCloseBrokerage = true
    }

    func clearError() {
        error = nil
    }

    func clearDeleteError() {
        deleteError = nil
    }

    func clearCloseBrokerageError() {
        closeBrokerageError = nil
    }

    /// Clears the one-shot success flag after the view has consumed it (post-dismiss).
    /// Prevents the auto-dismiss `.task(id:)` from re-firing if this VM is reused.
    func resetCloseBrokerageFlag() {
        didCloseBrokerage = false
    }

    // MARK: - Derived display state

    var displayName: String {
        guard let profile = profile?.profile else { return L10n.Settings.missingValuePlaceholder }
        if let preferred = profile.preferredName, !preferred.isEmpty {
            return preferred
        }
        var parts: [String] = []
        if let first = profile.firstName?.trimmingCharacters(in: .whitespaces), !first.isEmpty {
            parts.append(first)
        }
        if let last = profile.lastName?.trimmingCharacters(in: .whitespaces), !last.isEmpty {
            parts.append(last)
        }
        return parts.isEmpty ? L10n.Settings.missingValuePlaceholder : parts.joined(separator: " ")
    }

    var displayTier: String { L10n.Settings.tierFree }

    var displayInitials: String {
        let letters = displayName
            .split(separator: " ")
            .prefix(2)
            .compactMap { $0.first.map { String($0).uppercased() } }
            .joined()
        return letters.isEmpty ? L10n.Settings.missingValuePlaceholder : letters
    }

    var displayEmail: String {
        guard let email = profile?.profile.email, !email.isEmpty else {
            return L10n.Settings.missingValuePlaceholder
        }
        return email
    }

    var displayPhone: String {
        Self.formatPhone(profile?.profile.phoneNumber)
    }

    var displayAddress: String {
        guard let profile = profile?.profile else { return L10n.Settings.missingValuePlaceholder }
        let lines = profile.streetAddress ?? []
        let street = lines
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .joined(separator: ", ")

        var localityParts: [String] = []
        if let city = profile.city?.trimmingCharacters(in: .whitespaces), !city.isEmpty {
            localityParts.append(city)
        }
        if let state = profile.state?.trimmingCharacters(in: .whitespaces), !state.isEmpty {
            localityParts.append(state)
        }
        if let postal = profile.postalCode?.trimmingCharacters(in: .whitespaces), !postal.isEmpty {
            localityParts.append(postal)
        }
        let locality = localityParts.joined(separator: ", ")

        let combined = [street, locality]
            .filter { !$0.isEmpty }
            .joined(separator: ", ")
        return combined.isEmpty ? L10n.Settings.missingValuePlaceholder : combined
    }

    var displayRiskTolerance: String {
        Self.riskToleranceLabel(
            maxLoss: profile?.financialProfile?.maxLossTolerance,
            scenario: profile?.financialProfile?.riskScenarioResponse
        ) ?? L10n.Settings.missingValuePlaceholder
    }

    var displayMemberDuration: String? {
        guard let since = profile?.memberSinceDate else { return nil }
        return Self.formatMemberDuration(from: since, to: now(), calendar: .current)
    }

    // MARK: - Formatters (pure, testable)

    static func formatPhone(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return L10n.Settings.missingValuePlaceholder }
        let digits = raw.filter(\.isNumber)
        if digits.count == 11, digits.first == "1" {
            let area = digits.dropFirst().prefix(3)
            let mid = digits.dropFirst(4).prefix(3)
            let end = digits.dropFirst(7)
            return "+1 (\(area)) \(mid) \(end)"
        }
        if digits.count == 10 {
            let area = digits.prefix(3)
            let mid = digits.dropFirst(3).prefix(3)
            let end = digits.dropFirst(6)
            return "(\(area)) \(mid) \(end)"
        }
        return raw
    }

    /// Maps the stored onboarding selections to a display label that mirrors
    /// the backend's `derive_risk_tolerance` rule (see
    /// `app/services/onboarding.py`). Both inputs can arrive either as the
    /// backend's canonical form (`"0-5%"` / `"buy_more"`) or the raw UI label
    /// the user picked during onboarding (`"0 – 5% decline"` / `"Buy more and
    /// capitalize on the dip"`) — the DB stores whatever was submitted. We
    /// match on substrings to accept both shapes.
    static func riskToleranceLabel(maxLoss: String?, scenario: String?) -> String? {
        let loss = (maxLoss ?? "").lowercased()
        let scene = (scenario ?? "").lowercased()
        guard !loss.isEmpty || !scene.isEmpty else { return nil }

        let highLoss = loss.contains("25") || loss.contains("40")
        let lowLoss = !loss.isEmpty && !highLoss
            && (loss.contains("0-5") || loss.contains("0 – 5")
                || loss.contains("5-15") || loss.contains("5 – 15"))

        let wantsRisk = scene.contains("buy")
        let risksAverse = scene.contains("sell")

        if wantsRisk && highLoss { return L10n.Settings.riskAggressive }
        if risksAverse && lowLoss { return L10n.Settings.riskConservative }
        if lowLoss { return L10n.Settings.riskConservative }
        if highLoss { return wantsRisk ? L10n.Settings.riskAggressive : L10n.Settings.riskModerate }
        return L10n.Settings.riskModerate
    }

    static func formatMemberDuration(from start: Date, to end: Date, calendar: Calendar) -> String {
        guard end >= start else { return L10n.Settings.durationNone }
        let comps = calendar.dateComponents([.month, .day], from: start, to: end)
        let months = max(0, comps.month ?? 0)
        let leftoverDays = max(0, comps.day ?? 0)
        let weeks = leftoverDays / 7
        let days = leftoverDays % 7
        if months == 0 && weeks == 0 && days == 0 {
            return L10n.Settings.durationNone
        }
        return "\(L10n.Settings.durationMonths(months)), " +
            "\(L10n.Settings.durationWeeks(weeks)), " +
            "\(L10n.Settings.durationDays(days))"
    }
}

#if DEBUG
extension SettingsViewModel {
    /// Seeds `profile` synchronously for SwiftUI previews so the "loaded"
    /// state paints immediately instead of flashing the loading spinner.
    func seedProfileForPreview(_ profile: SettingsProfileResponse) {
        self.profile = profile
    }

    func seedErrorForPreview(_ message: String) {
        self.error = message
    }
}
#endif
