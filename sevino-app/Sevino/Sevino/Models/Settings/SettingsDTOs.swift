import Foundation

/// Profile data displayed on the settings screens.
struct SettingsProfileResponse: Decodable, Equatable {
    let displayName: String
    let email: String?
    let phoneNumber: String?
    let kycStatus: String?
}

/// Account value summary displayed at the top of settings.
struct AccountValueResponse: Decodable, Equatable {
    let totalValue: String
    let cashBalance: String
}
