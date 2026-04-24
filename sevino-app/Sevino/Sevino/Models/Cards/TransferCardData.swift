import Foundation

/// Bank account choice surfaced in the `TransferCard` selector. Mirrors the subset of
/// `AchRelationshipDTO` fields the card actually renders.
struct TransferBankAccount: Codable, Equatable, Identifiable, Hashable {
    let id: String
    let institutionName: String
    let accountMask: String
    let accountType: String
    let nickname: String?
}

/// Payload for an MCP `TransferCard`. The same struct backs both deposit and withdrawal
/// flows; the card derives its labelling, badge color, and validation from `direction`.
struct TransferCardData: Codable, Equatable {
    let direction: TransferDirection
    let bankAccounts: [TransferBankAccount]
    let brokerageLabel: String
    /// Maximum withdrawable cash. Set for `.withdraw` to enforce the cap; nil for `.deposit`.
    let availableBalance: Decimal?
    let currencyCode: String
}

/// Payload for an MCP `TransferConfirmationCard` — a read-only receipt the chatbot
/// surfaces after a transfer has been submitted.
struct TransferConfirmationData: Codable, Equatable {
    let direction: TransferDirection
    let amount: Decimal
    let currencyCode: String
    /// Institution name, e.g. "Chase". Drives the avatar glyph + primary row label.
    let bankInstitution: String
    /// Last four digits of the bank account, e.g. "4521".
    let bankMask: String
    /// Display-friendly account type, e.g. "Checking".
    let bankAccountType: String?
    /// Backend status string, e.g. "QUEUED", "COMPLETE", "FAILED".
    let status: String
    let createdAt: Date
    /// Human-readable settlement estimate ("Apr 28, 2026" or "1-3 business days").
    let estimatedSettlement: String?
    /// Failure reason, only surfaced for failed transfers ("ACH returned", etc.).
    let reason: String?
}

/// High-level bucket derived from the backend's transfer status string. Drives
/// the `TransferConfirmationCard` variant, pill colour, and glyph.
enum TransferStatusKind: Equatable {
    case queued
    case complete
    case failed
    case unknown

    static func from(_ status: String) -> TransferStatusKind {
        switch status.uppercased() {
        case "COMPLETE", "FILLED", "SETTLED":
            return .complete
        case "FAILED", "REJECTED", "CANCELED", "CANCELLED", "RETURNED":
            return .failed
        case "QUEUED", "PENDING", "APPROVAL_PENDING", "SUBMITTED":
            return .queued
        default:
            return .unknown
        }
    }
}
