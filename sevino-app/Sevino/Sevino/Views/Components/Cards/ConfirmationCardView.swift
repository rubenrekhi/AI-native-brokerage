import SwiftUI

/// Renders a `ConfirmationBlock` (the human-in-the-loop card).
///
/// Status-driven:
/// * `pending` → the proposal: amount/bank rows + a `HoldToConfirmButton` that
///   fires `onConfirm`, plus a Cancel affordance that fires `onCancel`.
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
        case "rejected": return "Cancelled"
        case "superseded": return "No longer available"
        case "expired": return "Expired"
        default: return "Closed"
        }
    }

    // MARK: - Shared pieces

    private var rowsStack: some View {
        VStack(alignment: .leading, spacing: 6 * scale) {
            ForEach(Array(block.rows.enumerated()), id: \.offset) { _, row in
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
            bankInstitution: d.bankInstitution ?? "Bank",
            bankMask: d.bankMask ?? "",
            bankAccountType: nil,
            status: status,
            createdAt: Date(),
            estimatedSettlement: nil,
            reason: d.reason
        )
    }
}
