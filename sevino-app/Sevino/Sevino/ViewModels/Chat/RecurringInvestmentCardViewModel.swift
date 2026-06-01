import Foundation
import Observation

@MainActor
@Observable
final class RecurringInvestmentCardViewModel {
    enum RecurringInvestmentState: Equatable, Sendable {
        case editing
        case submitting
        case scheduled
        case failed
    }

    /// Held independently of the canonical `endCondition` so switching tabs
    /// preserves the date / count the user last entered.
    enum EndKind: String, CaseIterable, Identifiable, Sendable {
        case never
        case onDate
        case afterCount

        var id: String { rawValue }
    }

    typealias SubmitHandler = (RecurringInvestmentRequest) async throws -> Void

    var block: RecurringInvestmentSetupBlock

    var amount: Decimal
    var frequency: RecurringFrequency
    var startDate: Date
    var endKind: EndKind
    var endDate: Date
    var occurrenceCount: Int

    private(set) var state: RecurringInvestmentState = .editing
    private(set) var error: String?

    private let onSubmit: SubmitHandler
    private let now: () -> Date

    init(
        block: RecurringInvestmentSetupBlock,
        onSubmit: @escaping SubmitHandler = { _ in try? await Task.sleep(for: .milliseconds(900)) },
        now: @escaping () -> Date = { .now }
    ) {
        self.block = block
        self.amount = block.defaultAmount
        self.frequency = block.defaultFrequency
        self.startDate = block.defaultStartDate
        self.onSubmit = onSubmit
        self.now = now

        let fallbackEndDate =
            Calendar.current.date(byAdding: .month, value: 1, to: block.defaultStartDate)
            ?? block.defaultStartDate
        switch block.defaultEndCondition {
        case .never:
            self.endKind = .never
            self.endDate = fallbackEndDate
            self.occurrenceCount = 12
        case .onDate(let date):
            self.endKind = .onDate
            self.endDate = date
            self.occurrenceCount = 12
        case .afterCount(let count):
            self.endKind = .afterCount
            self.endDate = fallbackEndDate
            self.occurrenceCount = count
        }
    }

    var endCondition: RecurringEndCondition {
        switch endKind {
        case .never: return .never
        case .onDate: return .onDate(endDate)
        case .afterCount: return .afterCount(occurrenceCount)
        }
    }

    var estimatedShares: Decimal {
        guard block.currentPrice > 0 else { return 0 }
        return amount / block.currentPrice
    }

    var minStartDate: Date {
        Calendar.current.startOfDay(for: now())
    }

    var minEndDate: Date {
        Calendar.current.date(byAdding: .day, value: 1, to: startDate) ?? startDate
    }

    var isValid: Bool { validationMessage == nil }

    /// Doubles as the inline hint explaining why the hold gesture is disabled.
    var validationMessage: String? {
        if amount <= 0 { return L10n.RecurringInvestment.invalidAmount }
        if startDate < minStartDate { return L10n.RecurringInvestment.invalidStartDate }
        switch endKind {
        case .never:
            return nil
        case .onDate:
            return endDate > startDate ? nil : L10n.RecurringInvestment.invalidEndDate
        case .afterCount:
            return occurrenceCount >= 1 ? nil : L10n.RecurringInvestment.invalidOccurrenceCount
        }
    }

    var summaryLine: String {
        let endClause: String
        switch endKind {
        case .never:
            endClause = ""
        case .onDate:
            endClause = L10n.RecurringInvestment.summaryEndsOn(Self.dayMonth(endDate))
        case .afterCount:
            endClause = L10n.RecurringInvestment.summaryEndsAfter(occurrenceCount)
        }
        return L10n.RecurringInvestment.summary(
            amount: amount.asCurrency(),
            cadence: Self.cadencePhrase(for: frequency),
            start: Self.dayMonth(startDate),
            endClause: endClause
        )
    }

    var firstBuyOnText: String {
        L10n.RecurringInvestment.firstBuyOn(Self.dayMonth(startDate))
    }

    var estimatedSharesSubline: String {
        L10n.RecurringInvestment.sharesSubline(
            estimatedShares.asShareCount(),
            block.currentPrice.asCurrency()
        )
    }

    func updateAmount(from text: String) {
        amount = Self.parseAmount(text)
    }

    func submit() async {
        guard isValid, state != .submitting, state != .scheduled else { return }
        state = .submitting
        error = nil
        do {
            try await onSubmit(makeRequest())
            state = .scheduled
        } catch {
            self.error = Self.message(for: error)
            state = .failed
        }
    }

    private func makeRequest() -> RecurringInvestmentRequest {
        RecurringInvestmentRequest(
            blockId: block.blockId,
            ticker: block.ticker,
            amount: amount,
            frequency: frequency,
            startDate: startDate,
            endCondition: endCondition
        )
    }

    private static func message(for error: Error) -> String {
        if let apiError = error as? APIError { return apiError.error }
        if let localized = error as? LocalizedError, let description = localized.errorDescription {
            return description
        }
        return L10n.RecurringInvestment.scheduleFailed
    }

    private static func cadencePhrase(for frequency: RecurringFrequency) -> String {
        switch frequency {
        case .weekly: return L10n.RecurringInvestment.cadenceWeekly
        case .biweekly: return L10n.RecurringInvestment.cadenceBiweekly
        case .monthly: return L10n.RecurringInvestment.cadenceMonthly
        }
    }

    private static func dayMonth(_ date: Date) -> String {
        date.formatted(.dateTime.month(.abbreviated).day())
    }

    /// Seed string for the editable amount field — the inverse of `parseAmount`,
    /// kept here so the view holds no `Decimal` text plumbing.
    static func amountText(_ amount: Decimal) -> String {
        NSDecimalNumber(decimal: amount).stringValue
    }

    private static func parseAmount(_ text: String) -> Decimal {
        let normalized = text.replacingOccurrences(of: ",", with: ".")
        return Decimal(string: normalized) ?? 0
    }
}

#if DEBUG
extension RecurringInvestmentCardViewModel {
    /// Builds a view model already seeded into `state` — used by previews to
    /// render the `.scheduled` / `.failed` surfaces without driving the async
    /// submit path. Same-file access lets it set the `private(set)` state.
    static func previewModel(
        block: RecurringInvestmentSetupBlock,
        state: RecurringInvestmentState = .editing,
        error: String? = nil,
        now: @escaping () -> Date = { .now }
    ) -> RecurringInvestmentCardViewModel {
        let model = RecurringInvestmentCardViewModel(block: block, now: now)
        model.state = state
        model.error = error
        return model
    }
}
#endif
