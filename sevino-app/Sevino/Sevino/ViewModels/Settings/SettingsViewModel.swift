import Foundation

@Observable
final class SettingsViewModel {
    private let settingsService: any SettingsServiceProtocol
    private let fundingService: any FundingServiceProtocol

    private(set) var profile: SettingsProfileResponse?
    private(set) var accountValue: AccountValueResponse?
    private(set) var isLoading = false
    private(set) var error: String?

    init(
        settingsService: any SettingsServiceProtocol = SettingsService.shared,
        fundingService: any FundingServiceProtocol = FundingService.shared
    ) {
        self.settingsService = settingsService
        self.fundingService = fundingService
    }

    func load() async {
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            async let profileResult = settingsService.getProfile()
            async let accountValueResult = settingsService.getAccountValue()
            profile = try await profileResult
            accountValue = try await accountValueResult
        } catch {
            self.error = error.localizedDescription
        }
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

    func clearError() {
        error = nil
    }
}
