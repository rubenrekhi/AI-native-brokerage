import Foundation

struct CashCardData: Codable, Equatable {
    let balance: Decimal
    let apy: Decimal
    let thisMonthEarned: Decimal
    let daysAccrued: Int
    let lifetimeEarned: Decimal
    let lifetimeSince: Date
    let buyingPower: Decimal
    let pendingDeposits: Decimal
    let interestPaidOut: PaidOutCadence
    let fdicInsuredLimit: Decimal
    let hasLinkedBank: Bool
}

enum PaidOutCadence: String, Codable, CaseIterable {
    case monthly
    case quarterly
    case annually
}
