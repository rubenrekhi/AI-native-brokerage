import Foundation

struct CashCardData: Codable, Equatable {
    let balance: Decimal
    let apy: Decimal
    let thisMonthEarned: Decimal
    let daysAccrued: Int
    let lifetimeEarned: Decimal
    let lifetimeSince: Date?
    let buyingPower: Decimal
    let pendingDeposits: Decimal
    let interestPaidOut: PaidOutCadence
    let fdicInsuredLimit: Decimal
    let enrollmentState: EnrollmentState
    let hasLinkedBank: Bool
    /// Non-nil when the bank needs Plaid re-auth. Transfers on a broken
    /// connection fail silently and create dispute resolution work, so
    /// callers must gate Deposit/Withdraw before allowing transfers.
    let reauthRelationshipId: UUID?
}

enum PaidOutCadence: String, Codable, CaseIterable {
    case monthly
    case quarterly
    case annually
}
