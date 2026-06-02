import SwiftUI

/// Renders a `ConfirmationBlock` (the human-in-the-loop card).
///
/// For the `transfer` kind it reuses the polished `TransferConfirmationCard` receipt
/// for every state and drops a `HoldToConfirmButton` beneath it while the proposal is
/// live. Holding fires `onConfirm`; afterwards the button falls away and the receipt
/// reflects the resolved status:
/// * `pending` → queued receipt + hold button (the proposal).
/// * `confirmed` / `executed` → queued/submitted receipt, no button.
/// * `failed` → failed receipt (the cause is narrated by the agent's reply,
///   not the card — `details` carries no failure reason).
/// * `rejected` / `superseded` / `expired` → the receipt, dimmed and dead.
///
/// Status is re-stamped server-side at read time and patched live via `block_data`,
/// so a resumed transcript renders the right state without client bookkeeping.
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
            if block.kind == "transfer", let data = transferData {
                transferCard(data)
            } else {
                genericCard
            }
        }
        .opacity(isDead ? 0.55 : 1)
        .animation(.easeInOut(duration: 0.25), value: block.status)
    }

    // MARK: - Transfer (the premium receipt)

    private func transferCard(_ data: TransferConfirmationData) -> some View {
        VStack(spacing: 12 * scale) {
            TransferConfirmationCard(data: data, scale: scale)
            if isPending {
                HoldToConfirmButton(title: holdTitle, scale: scale, action: onConfirm)
                    .padding(.horizontal, 4 * scale)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
        }
    }

    private var holdTitle: String {
        let direction = TransferDirection(rawValue: block.details.operation ?? "deposit") ?? .deposit
        return direction == .withdraw
            ? L10n.Confirmation.holdToWithdraw
            : L10n.Confirmation.holdToDeposit
    }

    private var transferData: TransferConfirmationData? {
        let d = block.details
        let direction = TransferDirection(rawValue: d.operation ?? "deposit") ?? .deposit
        let amount = Decimal(string: d.amount ?? "") ?? 0
        return TransferConfirmationData(
            direction: direction,
            amount: amount,
            currencyCode: d.currency ?? "USD",
            bankInstitution: d.bankInstitution ?? L10n.Confirmation.bankFallback,
            bankMask: d.bankMask ?? "",
            bankAccountType: nil,
            status: cardStatus,
            createdAt: stampedAt,
            estimatedSettlement: showsSettlement ? L10n.Confirmation.settlementEstimate : nil,
            reason: cardReason
        )
    }

    /// Maps the HIL block status onto the transfer-card status vocabulary
    /// (`TransferStatusKind`): submitted states read as `QUEUED`, dead ones as
    /// `CANCELED`, failures as `FAILED`.
    private var cardStatus: String {
        switch block.status {
        case "failed": return "FAILED"
        case "rejected", "superseded", "expired": return "CANCELED"
        default: return "QUEUED"
        }
    }

    private var showsSettlement: Bool {
        block.status == "confirmed" || block.status == "executed"
    }

    private var cardReason: String? {
        switch block.status {
        case "failed": return block.details.reason
        case "rejected": return L10n.Confirmation.statusCancelled
        case "superseded": return L10n.Confirmation.statusSuperseded
        case "expired": return L10n.Confirmation.statusExpired
        default: return nil
        }
    }

    // MARK: - Generic fallback (non-transfer HIL kinds)

    private var genericCard: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            Text(block.title)
                .font(.headline)
                .foregroundStyle(Color.sevinoSecondary)

            if !block.rows.isEmpty {
                VStack(alignment: .leading, spacing: 6 * scale) {
                    ForEach(block.rows, id: \.label) { row in
                        HStack {
                            Text(row.label)
                                .foregroundStyle(Color.sevinoSecondary.opacity(0.7))
                            Spacer()
                            Text(row.value)
                                .foregroundStyle(Color.sevinoSecondary)
                                .multilineTextAlignment(.trailing)
                        }
                        .font(.subheadline)
                    }
                }
            }

            if isPending {
                HoldToConfirmButton(title: block.confirmLabel, scale: scale, action: onConfirm)
            }
        }
        .padding(16 * scale)
        .background(
            RoundedRectangle(cornerRadius: 16 * scale, style: .continuous)
                .fill(Color.sevinoSecondary.opacity(0.08))
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
            rows: [
                ConfirmationRow(label: "Amount", value: "$500.00"),
                ConfirmationRow(label: "Transfer", value: "Chase ••1234 → Sevino"),
            ],
            details: ConfirmationDetails(
                operation: operation,
                direction: "INCOMING",
                amount: "500.00",
                currency: "USD",
                bankInstitution: "Chase",
                bankMask: "1234",
                bankNickname: "Checking",
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
            ConfirmationCardView(block: block("executed"))
            ConfirmationCardView(block: block("failed"))
            ConfirmationCardView(block: block("superseded"))
        }
        .padding()
    }
    .background(Color.sevinoPrimary)
    .preferredColorScheme(.dark)
}
