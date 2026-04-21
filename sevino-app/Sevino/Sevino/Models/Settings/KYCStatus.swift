import SwiftUI

enum KYCStatus: String {
    case onboarding = "ONBOARDING"
    case submitted = "SUBMITTED"
    case submissionFailed = "SUBMISSION_FAILED"
    case actionRequired = "ACTION_REQUIRED"
    case accountUpdated = "ACCOUNT_UPDATED"
    case approvalPending = "APPROVAL_PENDING"
    case approved = "APPROVED"
    case rejected = "REJECTED"
    case active = "ACTIVE"
    case inactive = "INACTIVE"
    case accountClosed = "ACCOUNT_CLOSED"

    var label: String {
        switch self {
        case .onboarding: L10n.Settings.kycOnboarding
        case .submitted: L10n.Settings.kycSubmitted
        case .submissionFailed: L10n.Settings.kycFailed
        case .actionRequired: L10n.Settings.kycActionRequired
        case .accountUpdated: L10n.Settings.kycUpdated
        case .approvalPending: L10n.Settings.kycPending
        case .approved: L10n.Settings.kycApproved
        case .rejected: L10n.Settings.kycRejected
        case .active: L10n.Settings.kycActive
        case .inactive: L10n.Settings.kycInactive
        case .accountClosed: L10n.Settings.kycClosed
        }
    }

    var color: Color {
        switch self {
        case .active, .approved:
            Color.sevinoPositive
        case .submitted, .approvalPending, .accountUpdated, .onboarding:
            Color.sevinoInfo
        case .actionRequired:
            Color.sevinoWarning
        case .rejected, .submissionFailed:
            Color.sevinoNegative
        case .inactive, .accountClosed:
            Color.sevinoGreyContrast
        }
    }
}
