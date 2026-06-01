import Foundation

/// What the chat host submits when the user holds to schedule a recurring buy.
struct RecurringInvestmentRequest: Equatable, Sendable {
    let blockId: String
    let ticker: String
    let amount: Decimal
    let frequency: RecurringFrequency
    let startDate: Date
    let endCondition: RecurringEndCondition
}
