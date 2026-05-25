import XCTest
@testable import Sevino

@MainActor
final class TransferViewModelTests: XCTestCase {

    private func makeSUT(
        mock: MockFundingService = MockFundingService()
    ) -> (TransferViewModel, MockFundingService) {
        (TransferViewModel(service: mock), mock)
    }

    private func makeResponse(
        id: String = "xfer_1",
        status: String = "QUEUED",
        amount: String = "500.00",
        direction: String = "INCOMING",
        bank: TransferBank? = nil,
        reason: String? = nil,
        createdAt: String? = "2026-04-24T12:34:56.789Z"
    ) -> TransferResponse {
        TransferResponse(
            id: id,
            status: status,
            amount: amount,
            direction: direction,
            createdAt: createdAt,
            reason: reason,
            bank: bank
        )
    }

    private func makeRelationship(
        id: UUID = UUID(),
        institutionName: String? = "Chase",
        accountMask: String? = "4521",
        accountType: String? = "CHECKING",
        nickname: String? = nil
    ) -> AchRelationshipDTO {
        AchRelationshipDTO(
            id: id,
            alpacaRelationshipId: "rel_\(id.uuidString.prefix(8))",
            institutionName: institutionName,
            accountMask: accountMask,
            accountType: accountType,
            nickname: nickname,
            status: "QUEUED",
            requiresReauth: false
        )
    }

    private func makeBank(
        id: String = "bank-1",
        institution: String = "Chase",
        mask: String = "4521",
        type: String = "CHECKING"
    ) -> TransferBankAccount {
        TransferBankAccount(
            id: id,
            institutionName: institution,
            accountMask: mask,
            accountType: type,
            nickname: nil
        )
    }

    // MARK: - start / cancel

    func test_start_setsDirectionAndClearsPriorConfirmation() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse())
        await sut.submit(bankAccountID: "rel-1", amount: 100, sourceBank: makeBank())
        XCTAssertNotNil(sut.confirmation)

        sut.start(direction: .withdraw)

        XCTAssertEqual(sut.direction, .withdraw)
        XCTAssertNil(sut.confirmation)
    }

    func test_cancel_resetsAllState() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse())
        await sut.submit(bankAccountID: "rel-1", amount: 100, sourceBank: makeBank())

        sut.cancel()

        XCTAssertNil(sut.direction)
        XCTAssertNil(sut.confirmation)
        XCTAssertFalse(sut.isSubmitting)
    }

    // MARK: - cardData

    func test_cardData_forDeposit_omitsAvailableBalance() {
        let (sut, _) = makeSUT()
        let rel = makeRelationship()

        let data = sut.cardData(
            for: .deposit,
            relationships: [rel],
            availableBalance: 2500,
            brokerageLabel: "Sevino"
        )

        XCTAssertEqual(data.direction, .deposit)
        XCTAssertNil(data.availableBalance)
        XCTAssertEqual(data.bankAccounts.count, 1)
        XCTAssertEqual(data.brokerageLabel, "Sevino")
    }

    func test_cardData_forWithdraw_includesAvailableBalance() {
        let (sut, _) = makeSUT()
        let rel = makeRelationship()

        let data = sut.cardData(
            for: .withdraw,
            relationships: [rel],
            availableBalance: 2500,
            brokerageLabel: "Sevino"
        )

        XCTAssertEqual(data.direction, .withdraw)
        XCTAssertEqual(data.availableBalance, 2500)
    }

    func test_cardData_mapsNilDTOFieldsToEmptyStrings() {
        let (sut, _) = makeSUT()
        let rel = makeRelationship(
            institutionName: nil,
            accountMask: nil,
            accountType: nil
        )

        let data = sut.cardData(
            for: .deposit,
            relationships: [rel],
            availableBalance: nil,
            brokerageLabel: "Sevino"
        )

        let bank = try? XCTUnwrap(data.bankAccounts.first)
        XCTAssertEqual(bank?.institutionName, "")
        XCTAssertEqual(bank?.accountMask, "")
        XCTAssertEqual(bank?.accountType, "")
    }

    // MARK: - submit

    func test_submit_withNilDirection_isNoOp() async {
        let (sut, mock) = makeSUT()
        // Direction defaults to nil.

        await sut.submit(bankAccountID: "rel-1", amount: 100, sourceBank: makeBank())

        XCTAssertTrue(mock.createTransferCalls.isEmpty)
        XCTAssertNil(sut.confirmation)
        XCTAssertFalse(sut.isSubmitting)
    }

    func test_submit_success_populatesConfirmationWithResponseAmount() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse(
            status: "QUEUED",
            amount: "500.00",
            bank: TransferBank(nickname: nil, accountMask: "4521", institutionName: "Chase")
        ))

        await sut.submit(bankAccountID: "rel-1", amount: 500, sourceBank: makeBank())

        XCTAssertEqual(mock.createTransferCalls.count, 1)
        XCTAssertEqual(mock.createTransferCalls.first?.relationshipId, "rel-1")
        XCTAssertEqual(mock.createTransferCalls.first?.amount, 500)
        XCTAssertEqual(mock.createTransferCalls.first?.direction, .deposit)

        let confirmation = try? XCTUnwrap(sut.confirmation)
        XCTAssertEqual(confirmation?.direction, .deposit)
        XCTAssertEqual(confirmation?.amount, 500)
        XCTAssertEqual(confirmation?.status, "QUEUED")
        XCTAssertEqual(confirmation?.currencyCode, "USD")
        XCTAssertFalse(sut.isSubmitting)
    }

    func test_submit_fallsBackToInputAmount_whenResponseAmountIsZero() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse(amount: "0"))

        await sut.submit(bankAccountID: "rel-1", amount: 123, sourceBank: makeBank())

        XCTAssertEqual(sut.confirmation?.amount, 123)
    }

    func test_submit_onAPIError_surfacesFailedConfirmationWithReason() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .withdraw)
        let apiError = APIError(error: "Insufficient funds", code: "INSUFFICIENT_FUNDS")
        mock.createTransferResult = .failure(apiError)

        await sut.submit(bankAccountID: "rel-1", amount: 100, sourceBank: makeBank())

        XCTAssertEqual(sut.confirmation?.status, "FAILED")
        XCTAssertEqual(sut.confirmation?.reason, "Insufficient funds")
        XCTAssertEqual(sut.confirmation?.amount, 100)
        XCTAssertFalse(sut.isSubmitting)
    }

    func test_submit_onGenericError_surfacesFailedConfirmation() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .failure(URLError(.notConnectedToInternet))

        await sut.submit(bankAccountID: "rel-1", amount: 100, sourceBank: makeBank())

        XCTAssertEqual(sut.confirmation?.status, "FAILED")
        XCTAssertEqual(sut.confirmation?.reason, L10n.Home.fundingGenericError)
    }

    func test_submit_onURLCancelled_leavesConfirmationUnset() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .failure(URLError(.cancelled))

        await sut.submit(bankAccountID: "rel-1", amount: 100, sourceBank: makeBank())

        XCTAssertNil(sut.confirmation)
        XCTAssertFalse(sut.isSubmitting)
    }

    // MARK: - bank fields

    func test_submit_populatesBankFields_fromResponse() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse(
            bank: TransferBank(nickname: nil, accountMask: "4521", institutionName: "Chase")
        ))

        await sut.submit(
            bankAccountID: "rel-1",
            amount: 100,
            sourceBank: makeBank(institution: "Chase", mask: "4521", type: "CHECKING")
        )

        XCTAssertEqual(sut.confirmation?.bankInstitution, "Chase")
        XCTAssertEqual(sut.confirmation?.bankMask, "4521")
        XCTAssertEqual(sut.confirmation?.bankAccountType, "Checking")
    }

    func test_submit_fallsBackToSourceBank_whenResponseBankIsNil() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse(bank: nil))

        await sut.submit(
            bankAccountID: "rel-1",
            amount: 100,
            sourceBank: makeBank(institution: "Ally", mask: "7733", type: "SAVINGS")
        )

        XCTAssertEqual(sut.confirmation?.bankInstitution, "Ally")
        XCTAssertEqual(sut.confirmation?.bankMask, "7733")
        XCTAssertEqual(sut.confirmation?.bankAccountType, "Savings")
    }

    func test_submit_forwardsReason_forFailedTransfers() async {
        let (sut, mock) = makeSUT()
        sut.start(direction: .deposit)
        mock.createTransferResult = .success(makeResponse(
            status: "FAILED",
            bank: TransferBank(nickname: nil, accountMask: "0255", institutionName: "Wells Fargo"),
            reason: "ACH returned"
        ))

        await sut.submit(
            bankAccountID: "rel-1",
            amount: 2500,
            sourceBank: makeBank(institution: "Wells Fargo", mask: "0255")
        )

        XCTAssertEqual(sut.confirmation?.status, "FAILED")
        XCTAssertEqual(sut.confirmation?.reason, "ACH returned")
    }

    // MARK: - TransferStatusKind.from

    func test_statusKind_mapsKnownStatusesCaseInsensitively() {
        XCTAssertEqual(TransferStatusKind.from("COMPLETE"), .complete)
        XCTAssertEqual(TransferStatusKind.from("complete"), .complete)
        XCTAssertEqual(TransferStatusKind.from("Filled"), .complete)
        XCTAssertEqual(TransferStatusKind.from("SETTLED"), .complete)

        XCTAssertEqual(TransferStatusKind.from("QUEUED"), .queued)
        XCTAssertEqual(TransferStatusKind.from("pending"), .queued)
        XCTAssertEqual(TransferStatusKind.from("Approval_Pending"), .queued)
        XCTAssertEqual(TransferStatusKind.from("SUBMITTED"), .queued)

        XCTAssertEqual(TransferStatusKind.from("FAILED"), .failed)
        XCTAssertEqual(TransferStatusKind.from("rejected"), .failed)
        XCTAssertEqual(TransferStatusKind.from("CANCELED"), .failed)
        XCTAssertEqual(TransferStatusKind.from("CANCELLED"), .failed)
        XCTAssertEqual(TransferStatusKind.from("returned"), .failed)
    }

    func test_statusKind_unknownStatusMapsToUnknown() {
        XCTAssertEqual(TransferStatusKind.from("mystery"), .unknown)
        XCTAssertEqual(TransferStatusKind.from(""), .unknown)
    }
}
