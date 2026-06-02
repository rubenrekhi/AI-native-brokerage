import SwiftUI

/// Renders a `ConfirmationBlock` (the human-in-the-loop card).
///
/// Status-driven:
/// * `pending` → the proposal: amount/bank rows + a `HoldToConfirmButton` that
///   fires `onConfirm`, plus a Cancel affordance that fires `onCancel`.
/// * `confirmed` → just tapped; the side effect is in flight (optimistic local
///   state until read-time resolution flips it to `executed`).
/// * `executed` / `failed` (kind `transfer`) → the read-only `TransferConfirmationCard`
///   receipt, built from `details`.
/// * `rejected` / `superseded` / `expired` (or any other) → a dimmed, dead card.
///
/// The status is re-stamped server-side at read time, so a resumed transcript
/// renders the right state without any client bookkeeping.
struct ConfirmationCardView: View {
    let block: ConfirmationBlock
    var scale: CGFloat = 1
    /// Tapped/held Confirm — the parent POSTs `confirm` to the action endpoint.
    var onConfirm: () -> Void = {}
    /// Tapped Cancel — the parent POSTs `reject`.
    var onCancel: () -> Void = {}

    var body: some View {
        switch block.status {
        case "pending":
            pendingCard
        case "confirmed":
            processingCard
        case "executed", "failed":
            receiptCard
        default:
            deadCard
        }
    }

    // MARK: - Pending (the proposal)

    private var pendingCard: some View {
        VStack(alignment: .leading, spacing: 12 * scale) {
            Text(block.title)
                .font(.headline)
                .foregroundStyle(Color.sevinoSecondary)

            rowsStack

            HoldToConfirmButton(
                title: block.confirmLabel,
                scale: scale,
                action: onConfirm
            )

            Button(action: onCancel) {
                Text(block.cancelLabel)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.sevinoSecondary.opacity(0.7))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.plain)
        }
        .padding(16 * scale)
        .background(cardBackground)
    }

    // MARK: - Receipt (executed / failed)

    @ViewBuilder
    private var receiptCard: some View {
        if block.kind == "transfer", let data = transferReceiptData {
            TransferConfirmationCard(data: data, scale: scale)
        } else {
            deadCard
        }
    }

    // MARK: - Processing (just confirmed, side effect in flight)

    private var processingCard: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(block.title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.sevinoSecondary)
            rowsStack
            HStack(spacing: 6 * scale) {
                ProgressView().controlSize(.small)
                Text(L10n.Confirmation.statusProcessing)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Color.sevinoSecondary.opacity(0.7))
            }
        }
        .padding(14 * scale)
        .background(cardBackground)
    }

    // MARK: - Dead (rejected / superseded / expired / fallback)

    private var deadCard: some View {
        VStack(alignment: .leading, spacing: 8 * scale) {
            Text(block.title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.sevinoSecondary.opacity(0.55))
            rowsStack
            Text(deadLabel)
                .font(.caption.weight(.medium))
                .foregroundStyle(Color.sevinoSecondary.opacity(0.5))
        }
        .padding(14 * scale)
        .background(cardBackground)
        .opacity(0.6)
    }

    private var deadLabel: String {
        switch block.status {
        case "rejected": return L10n.Confirmation.statusCancelled
        case "superseded": return L10n.Confirmation.statusSuperseded
        case "expired": return L10n.Confirmation.statusExpired
        default: return L10n.Confirmation.statusClosed
        }
    }

    // MARK: - Shared pieces

    private var rowsStack: some View {
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

    private var cardBackground: some View {
        RoundedRectangle(cornerRadius: 16 * scale, style: .continuous)
            .fill(Color.sevinoSecondary.opacity(0.08))
    }

    private var transferReceiptData: TransferConfirmationData? {
        let d = block.details
        let direction = TransferDirection(rawValue: d.operation ?? "deposit")
            ?? .deposit
        let amount = Decimal(string: d.amount ?? "") ?? 0
        let status: String =
            block.status == "failed" ? "FAILED" : (d.transferStatus ?? "QUEUED")
        return TransferConfirmationData(
            direction: direction,
            amount: amount,
            currencyCode: d.currency ?? "USD",
            bankInstitution: d.bankInstitution ?? L10n.Confirmation.bankFallback,
            bankMask: d.bankMask ?? "",
            bankAccountType: nil,
            status: status,
            createdAt: .now,
            estimatedSettlement: nil,
            reason: d.reason
        )
    }
}

#Preview {
    func block(_ status: String) -> ConfirmationBlock {
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
                operation: "deposit",
                direction: "INCOMING",
                amount: "500.00",
                currency: "USD",
                bankInstitution: "Chase",
                bankMask: "1234",
                bankNickname: "Checking",
                transferId: nil,
                transferStatus: "QUEUED",
                reason: nil
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
            ConfirmationCardView(block: block("superseded"))
        }
        .padding()
    }
    .background(Color.sevinoPrimary)
    .preferredColorScheme(.dark)
}
