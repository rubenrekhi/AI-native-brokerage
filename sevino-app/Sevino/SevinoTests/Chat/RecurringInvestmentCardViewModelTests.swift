import XCTest
@testable import Sevino

@MainActor
final class RecurringInvestmentCardViewModelTests: XCTestCase {

    /// Fixed clock so "future start date" validation is deterministic.
    private let referenceNow = Date(timeIntervalSince1970: 1_780_000_000)

    private func makeBlock(
        currentPrice: Decimal = 100,
        defaultAmount: Decimal = 200,
        frequency: RecurringFrequency = .biweekly,
        startOffsetDays: Int = 3,
        endCondition: RecurringEndCondition = .never
    ) -> RecurringInvestmentSetupBlock {
        let start = Calendar.current.date(byAdding: .day, value: startOffsetDays, to: referenceNow)!
        return RecurringInvestmentSetupBlock(
            blockId: "blk_ri",
            ticker: "AAPL",
            companyName: "Apple Inc.",
            exchange: "NASDAQ",
            currentPrice: currentPrice,
            defaultAmount: defaultAmount,
            defaultFrequency: frequency,
            defaultStartDate: start,
            defaultEndCondition: endCondition,
            disclaimer: "x"
        )
    }

    private func makeModel(
        block: RecurringInvestmentSetupBlock? = nil,
        onSubmit: @escaping RecurringInvestmentCardViewModel.SubmitHandler = { _ in }
    ) -> RecurringInvestmentCardViewModel {
        RecurringInvestmentCardViewModel(
            block: block ?? makeBlock(),
            onSubmit: onSubmit,
            now: { [referenceNow] in referenceNow }
        )
    }

    // MARK: - Defaults

    func testDefaultsHydrateFromBlock() {
        let block = makeBlock(defaultAmount: 250, frequency: .monthly, endCondition: .afterCount(24))
        let model = makeModel(block: block)

        XCTAssertEqual(model.amount, 250)
        XCTAssertEqual(model.frequency, .monthly)
        XCTAssertEqual(model.startDate, block.defaultStartDate)
        XCTAssertEqual(model.endKind, .afterCount)
        XCTAssertEqual(model.occurrenceCount, 24)
        XCTAssertEqual(model.state, .editing)
        XCTAssertNil(model.error)
    }

    func testDefaultsHydrateOnDateEndCondition() {
        let endDate = Calendar.current.date(byAdding: .day, value: 60, to: referenceNow)!
        let model = makeModel(block: makeBlock(endCondition: .onDate(endDate)))

        XCTAssertEqual(model.endKind, .onDate)
        XCTAssertEqual(model.endDate, endDate)
    }

    // MARK: - Validation

    func testValidConfigurationIsValid() {
        let model = makeModel()
        XCTAssertTrue(model.isValid)
        XCTAssertNil(model.validationMessage)
    }

    func testZeroAmountIsInvalid() {
        let model = makeModel()
        model.amount = 0
        XCTAssertFalse(model.isValid)
        XCTAssertEqual(model.validationMessage, L10n.RecurringInvestment.invalidAmount)
    }

    func testPastStartDateIsInvalid() {
        let model = makeModel()
        model.startDate = Calendar.current.date(byAdding: .day, value: -1, to: referenceNow)!
        XCTAssertFalse(model.isValid)
        XCTAssertEqual(model.validationMessage, L10n.RecurringInvestment.invalidStartDate)
    }

    func testEndDateBeforeStartIsInvalid() {
        let model = makeModel()
        model.endKind = .onDate
        model.endDate = Calendar.current.date(byAdding: .day, value: -1, to: model.startDate)!
        XCTAssertFalse(model.isValid)
        XCTAssertEqual(model.validationMessage, L10n.RecurringInvestment.invalidEndDate)
    }

    func testZeroOccurrencesIsInvalid() {
        let model = makeModel()
        model.endKind = .afterCount
        model.occurrenceCount = 0
        XCTAssertFalse(model.isValid)
        XCTAssertEqual(model.validationMessage, L10n.RecurringInvestment.invalidOccurrenceCount)
    }

    // MARK: - Submit

    func testSubmitHappyPathTransitionsToScheduled() async {
        let model = makeModel(onSubmit: { _ in })
        await model.submit()
        XCTAssertEqual(model.state, .scheduled)
        XCTAssertNil(model.error)
    }

    func testSubmitPassesCurrentFormStateToHandler() async {
        var captured: RecurringInvestmentRequest?
        let model = makeModel(onSubmit: { captured = $0 })
        model.amount = 321
        model.frequency = .weekly

        await model.submit()

        XCTAssertEqual(captured?.amount, 321)
        XCTAssertEqual(captured?.frequency, .weekly)
        XCTAssertEqual(captured?.ticker, "AAPL")
        XCTAssertEqual(captured?.endCondition, .never)
    }

    func testDailyFrequencyUsesDailyCadenceInSummary() {
        let model = makeModel(block: makeBlock(frequency: .daily))
        XCTAssertEqual(model.frequency, .daily)
        XCTAssertTrue(model.summaryLine.contains(L10n.RecurringInvestment.cadenceDaily))
    }

    func testSubmitFailureTransitionsToFailedAndReenablesForm() async {
        struct StubError: LocalizedError { var errorDescription: String? { "scheduler offline" } }
        let model = makeModel(onSubmit: { _ in throw StubError() })

        await model.submit()

        XCTAssertEqual(model.state, .failed)
        XCTAssertEqual(model.error, "scheduler offline")
        XCTAssertTrue(model.isValid, "a valid form stays submittable so the user can re-hold to retry")
    }

    func testSubmitIgnoredWhenInvalid() async {
        let model = makeModel(onSubmit: { _ in XCTFail("handler should not run for an invalid form") })
        model.amount = 0
        await model.submit()
        XCTAssertEqual(model.state, .editing)
    }

    // MARK: - Estimated shares

    func testEstimatedSharesRecomputesWhenAmountChanges() {
        let model = makeModel(block: makeBlock(currentPrice: 100, defaultAmount: 200))
        XCTAssertEqual(model.estimatedShares, 2)
        model.amount = 500
        XCTAssertEqual(model.estimatedShares, 5)
    }

    func testEstimatedSharesRecomputesWhenCurrentPriceChanges() {
        let model = makeModel(block: makeBlock(currentPrice: 100, defaultAmount: 200))
        XCTAssertEqual(model.estimatedShares, 2)
        model.block = makeBlock(currentPrice: 50, defaultAmount: 200)
        XCTAssertEqual(model.estimatedShares, 4)
    }

    func testEstimatedSharesIsZeroWhenPriceIsZero() {
        let model = makeModel(block: makeBlock(currentPrice: 0))
        XCTAssertEqual(model.estimatedShares, 0)
    }
}
