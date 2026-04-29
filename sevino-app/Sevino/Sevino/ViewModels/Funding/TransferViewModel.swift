import Foundation
import Observation

/// Drives the temporary home-screen transfer flow until the chat backend can host
/// `TransferCard` as an MCP component. Owns the form/confirmation state and the
/// network call that submits the ACH transfer.
@Observable
final class TransferViewModel {

    /// Active transfer direction. `nil` means no transfer card is shown.
    private(set) var direction: TransferDirection?

    /// Receipt rendered after a successful submission. When set, the parent view
    /// should swap `TransferCard` for `TransferConfirmationCard`.
    private(set) var confirmation: TransferConfirmationData?

    private(set) var isSubmitting: Bool = false

    private let service: any FundingServiceProtocol

    init(service: any FundingServiceProtocol = FundingService.shared) {
        self.service = service
    }

    // MARK: - Lifecycle

    func start(direction: TransferDirection) {
        self.direction = direction
        confirmation = nil
    }

    func cancel() {
        direction = nil
        confirmation = nil
        isSubmitting = false
    }

    // MARK: - Card data

    /// Build a `TransferCardData` for the given direction from the funding view model's
    /// linked relationships and (for withdrawals) buying-power cap.
    func cardData(
        for direction: TransferDirection,
        relationships: [AchRelationshipDTO],
        availableBalance: Decimal?,
        brokerageLabel: String,
        currencyCode: String = "USD"
    ) -> TransferCardData {
        TransferCardData(
            direction: direction,
            bankAccounts: relationships.map { TransferBankAccount(from: $0) },
            brokerageLabel: brokerageLabel,
            availableBalance: direction == .withdraw ? availableBalance : nil,
            currencyCode: currencyCode
        )
    }

    // MARK: - Submission

    func submit(
        bankAccountID: String,
        amount: Decimal,
        sourceBank: TransferBankAccount?
    ) async {
        guard let direction else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            let response = try await service.createTransfer(
                relationshipId: bankAccountID,
                amount: amount,
                direction: direction
            )
            confirmation = TransferConfirmationData(
                direction: direction,
                amount: response.amountValue == 0 ? amount : response.amountValue,
                currencyCode: "USD",
                bankInstitution: response.bank?.institutionName ?? sourceBank?.institutionName ?? "",
                bankMask: response.bank?.accountMask ?? sourceBank?.accountMask ?? "",
                bankAccountType: sourceBank?.accountType.capitalized,
                status: response.status,
                createdAt: response.createdAtDate ?? .now,
                estimatedSettlement: L10n.Transfer.disclaimer,
                reason: response.reason
            )
        } catch is CancellationError {
            return
        } catch let urlError as URLError where urlError.code == .cancelled {
            return
        } catch let apiError as APIError {
            // Surface backend validation/business errors through the designed
            // failed-confirmation card instead of a system alert.
            confirmation = failedConfirmation(
                direction: direction,
                amount: amount,
                sourceBank: sourceBank,
                reason: apiError.error
            )
        } catch {
            confirmation = failedConfirmation(
                direction: direction,
                amount: amount,
                sourceBank: sourceBank,
                reason: L10n.Home.fundingGenericError
            )
        }
    }

    private func failedConfirmation(
        direction: TransferDirection,
        amount: Decimal,
        sourceBank: TransferBankAccount?,
        reason: String
    ) -> TransferConfirmationData {
        TransferConfirmationData(
            direction: direction,
            amount: amount,
            currencyCode: "USD",
            bankInstitution: sourceBank?.institutionName ?? "",
            bankMask: sourceBank?.accountMask ?? "",
            bankAccountType: sourceBank?.accountType.capitalized,
            status: "FAILED",
            createdAt: .now,
            estimatedSettlement: nil,
            reason: reason
        )
    }
}

private extension TransferBankAccount {
    init(from dto: AchRelationshipDTO) {
        self.init(
            id: dto.id.uuidString,
            institutionName: dto.institutionName ?? "",
            accountMask: dto.accountMask ?? "",
            accountType: dto.accountType ?? "",
            nickname: dto.nickname
        )
    }
}
