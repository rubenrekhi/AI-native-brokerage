import SwiftUI

/// Renders a `ConfirmationBlock` (the human-in-the-loop transfer card).
///
/// While the proposal is live it shows the `TransferCard` with a fixed,
/// AI-prefilled amount and a hold-to-confirm button. Once Alpaca confirms the
/// transfer (status `executed`), the card transforms into the
/// `TransferConfirmationCard` receipt; a failure shows the receipt's failed
/// variant. Status is re-stamped server-side at read time and patched live via
/// `block_data`, so the right state renders on resume or reload.
struct ConfirmationCardView: View {
    let block: ConfirmationBlock
    var scale: CGFloat = 1
    /// Held Confirm — the parent POSTs `confirm` to the action endpoint.
    var onConfirm: () -> Void = {}

    /// Stamped once when the card first appears so the receipt's submitted-time
    /// row stays put across recomputes (the block carries no timestamp).
    @State private var stampedAt = Date()

    private var isPending: Bool { block.status == "pending" }

    private var isDead: Bool {
        switch block.status {
        case "rejected", "superseded", "expired": return true
        default: return false
        }
    }

    var body: some View {
        Group {
            switch block.status {
            case "executed", "failed":
                TransferConfirmationCard(data: receiptData, scale: scale)
            default:
                TransferCard(
                    data: proposalData,
                    scale: scale,
                    prefilledAmount: amount,
                    onHoldConfirm: isPending ? onConfirm : nil,
                    isSubmitting: block.status == "confirmed",
                    holdTitle: holdTitle
                )
                .opacity(isDead ? 0.55 : 1)
            }
        }
        .padding(.horizontal, 16 * scale)
        .animation(.easeInOut(duration: 0.25), value: block.status)
    }

    // MARK: - Derived data

    private var direction: TransferDirection {
        TransferDirection(rawValue: block.details.operation ?? "deposit") ?? .deposit
    }

    private var amount: Decimal {
        Decimal(string: block.details.amount ?? "") ?? 0
    }

    private var holdTitle: String {
        direction == .withdraw
            ? L10n.Confirmation.holdToWithdraw
            : L10n.Confirmation.holdToDeposit
    }

    /// The proposal, mapped onto `TransferCard`. The AI has already resolved a
    /// single bank, so the card shows it read-only (no picker, no entry).
    private var proposalData: TransferCardData {
        let d = block.details
        let bank = TransferBankAccount(
            id: "proposed",
            institutionName: d.bankInstitution ?? L10n.Confirmation.bankFallback,
            accountMask: d.bankMask ?? "",
            accountType: "",
            nickname: d.bankNickname
        )
        return TransferCardData(
            direction: direction,
            bankAccounts: [bank],
            brokerageLabel: L10n.Transfer.brokerageName,
            availableBalance: nil,
            currencyCode: d.currency ?? "USD"
        )
    }

    /// The receipt shown after confirmation. A successful transfer reads as
    /// `QUEUED` (submitted, settling); a failure shows the failed variant.
    private var receiptData: TransferConfirmationData {
        let d = block.details
        let failed = block.status == "failed"
        return TransferConfirmationData(
            direction: direction,
            amount: amount,
            currencyCode: d.currency ?? "USD",
            bankInstitution: d.bankInstitution ?? L10n.Confirmation.bankFallback,
            bankMask: d.bankMask ?? "",
            bankAccountType: nil,
            status: failed ? "FAILED" : "QUEUED",
            createdAt: stampedAt,
            estimatedSettlement: failed ? nil : L10n.Confirmation.settlementEstimate,
            reason: failed ? d.reason : nil
        )
    }
}

#Preview {
    func block(_ status: String, operation: String = "deposit") -> ConfirmationBlock {
        ConfirmationBlock(
            blockId: "blk-\(status)",
            actionId: "act-\(status)",
            kind: "transfer",
            title: "Confirm deposit",
            rows: [],
            details: ConfirmationDetails(
                operation: operation,
                direction: "INCOMING",
                amount: "500.00",
                currency: "USD",
                bankInstitution: "Chase",
                bankMask: "4821",
                bankNickname: nil,
                transferId: nil,
                transferStatus: "QUEUED",
                reason: status == "failed" ? "Insufficient funds at your bank" : nil
            ),
            confirmLabel: "Confirm deposit",
            cancelLabel: "Cancel",
            holdToConfirm: true,
            status: status
        )
    }
    return ScrollView {
        VStack(spacing: 16) {
            ConfirmationCardView(block: block("pending"))
            ConfirmationCardView(block: block("confirmed"))
            ConfirmationCardView(block: block("executed"))
            ConfirmationCardView(block: block("failed"))
        }
        .padding()
    }
    .background(Color.sevinoPrimary)
    .preferredColorScheme(.dark)
}
