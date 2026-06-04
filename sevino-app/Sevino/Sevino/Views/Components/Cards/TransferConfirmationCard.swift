import SwiftUI

/// Read-only receipt the chatbot surfaces after a transfer has been submitted.
///
/// Two visual variants driven by `data.status`:
/// * **Hero** (queued/pending/complete) — large glyph, status pill, key-value rows.
/// * **Failed** (rejected/failed/canceled) — red accent stripe, compact one-row layout
///   with a failure reason.
struct TransferConfirmationCard: View {
    let data: TransferConfirmationData
    var scale: CGFloat = 1
    var onDismiss: (() -> Void)?

    private var kind: TransferStatusKind { TransferStatusKind.from(data.status) }

    var body: some View {
        Group {
            switch kind {
            case .failed:
                TransferFailedReceipt(data: data, scale: scale, onDismiss: onDismiss)
            case .complete:
                TransferCompactReceipt(data: data, scale: scale, kind: kind, onDismiss: onDismiss)
            case .queued, .unknown:
                TransferHeroReceipt(data: data, scale: scale, kind: kind, onDismiss: onDismiss)
            }
        }
    }
}

// MARK: - Status kind visual mapping

private extension TransferStatusKind {
    var label: String {
        switch self {
        case .queued: L10n.Transfer.statusQueued
        case .complete: L10n.Transfer.statusComplete
        case .failed: L10n.Transfer.statusFailed
        case .unknown: L10n.Transfer.statusUnknown
        }
    }

    var color: Color {
        switch self {
        case .queued, .unknown: TransferPalette.withdrawAmber
        case .complete: TransferPalette.depositGreen
        case .failed: TransferPalette.failRed
        }
    }

    var mutedColor: Color {
        switch self {
        case .queued, .unknown: TransferPalette.withdrawAmberMuted
        case .complete: TransferPalette.depositGreenMuted
        case .failed: TransferPalette.failRedMuted
        }
    }

    var glyph: String {
        switch self {
        case .queued, .unknown: "clock"
        case .complete: "checkmark"
        case .failed: "xmark"
        }
    }
}

// MARK: - Hero receipt (queued / complete)

private struct TransferHeroReceipt: View {
    let data: TransferConfirmationData
    let scale: CGFloat
    let kind: TransferStatusKind
    let onDismiss: (() -> Void)?

    private var bankDisplay: String {
        L10n.Transfer.bankAccountFormat(data.bankInstitution, data.bankMask)
    }

    var body: some View {
        VStack(spacing: 18 * scale) {
            HStack(spacing: 10 * scale) {
                TransferDirectionBadge(direction: data.direction, scale: scale)
                Spacer()
                Text(L10n.Transfer.receiptLabel)
                    .font(.system(size: 11 * scale, weight: .semibold))
                    .tracking(1.4)
                    .foregroundStyle(TransferPalette.textFaint)
                if let onDismiss {
                    Button(action: onDismiss) {
                        Image(systemName: "xmark")
                            .font(.system(size: 12 * scale, weight: .bold))
                            .foregroundStyle(TransferPalette.textSecondary)
                            .frame(width: 28 * scale, height: 28 * scale)
                            .background(Circle().fill(TransferPalette.iconBgSubtle))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.Transfer.closeAccessibility)
                }
            }

            VStack(spacing: 10 * scale) {
                Image(systemName: kind.glyph)
                    .font(.system(size: 18 * scale, weight: .bold))
                    .foregroundStyle(kind.color)
                    .frame(width: 44 * scale, height: 44 * scale)
                    .background(
                        Circle().stroke(kind.color.opacity(0.35), lineWidth: 1.5)
                    )
                    .background(Circle().fill(kind.mutedColor))

                Text(data.amount.formatted(.currency(code: data.currencyCode)))
                    .font(.system(size: 36 * scale, weight: .bold))
                    .foregroundStyle(TransferPalette.textPrimary)

                TransferStatusPill(kind: kind, scale: scale)
            }

            Rectangle()
                .fill(TransferPalette.hairline)
                .frame(height: 1)

            VStack(spacing: 10 * scale) {
                KVRow(label: L10n.Transfer.fromLabel, value: bankDisplay, scale: scale)
                KVRow(label: L10n.Transfer.submittedLabel.capitalized,
                      value: data.createdAt.formatted(date: .abbreviated, time: .shortened),
                      scale: scale)
                if let estimate = data.estimatedSettlement {
                    KVRow(label: L10n.Transfer.estimatedArrivalLabel, value: estimate, scale: scale)
                }
            }
        }
        .padding(20 * scale)
        .frame(maxWidth: .infinity)
        .background(GenUICardBackground(cornerRadius: 28 * scale))
    }
}

private struct TransferStatusPill: View {
    let kind: TransferStatusKind
    let scale: CGFloat

    var body: some View {
        Text(kind.label)
            .font(.system(size: 12 * scale, weight: .bold))
            .foregroundStyle(kind.color)
            .padding(.horizontal, 12 * scale)
            .padding(.vertical, 5 * scale)
            .background(Capsule().fill(kind.mutedColor))
    }
}

private struct KVRow: View {
    let label: String
    let value: String
    let scale: CGFloat

    var body: some View {
        HStack(alignment: .top, spacing: 12 * scale) {
            Text(label)
                .font(.system(size: 13 * scale))
                .foregroundStyle(TransferPalette.textTertiary)
                .fixedSize(horizontal: true, vertical: false)
            Spacer(minLength: 0)
            Text(value)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(TransferPalette.textPrimary)
                .multilineTextAlignment(.trailing)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: - Compact receipt (complete)

private struct TransferCompactReceipt: View {
    let data: TransferConfirmationData
    let scale: CGFloat
    let kind: TransferStatusKind
    let onDismiss: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            HStack(spacing: 10 * scale) {
                TransferDirectionBadge(direction: data.direction, scale: scale)
                Spacer()
                TransferStatusDotPill(kind: kind, scale: scale)
                if let onDismiss {
                    Button(action: onDismiss) {
                        Image(systemName: "xmark")
                            .font(.system(size: 12 * scale, weight: .bold))
                            .foregroundStyle(TransferPalette.textSecondary)
                            .frame(width: 28 * scale, height: 28 * scale)
                            .background(Circle().fill(TransferPalette.iconBgSubtle))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.Transfer.closeAccessibility)
                }
            }

            Text(data.amount.formatted(.currency(code: data.currencyCode)))
                .font(.system(size: 34 * scale, weight: .bold))
                .foregroundStyle(TransferPalette.textPrimary)

            TransferCompactFlow(data: data, scale: scale)

            Rectangle()
                .fill(TransferPalette.hairline)
                .frame(height: 1)

            HStack(alignment: .top) {
                metaColumn(
                    title: L10n.Transfer.submittedLabel,
                    value: data.createdAt.formatted(date: .abbreviated, time: .shortened),
                    alignment: .leading
                )
                Spacer(minLength: 0)
                if let settles = data.estimatedSettlement {
                    metaColumn(
                        title: L10n.Transfer.settlesLabel,
                        value: settles,
                        alignment: .trailing
                    )
                }
            }
        }
        .padding(20 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GenUICardBackground(cornerRadius: 28 * scale))
    }

    private func metaColumn(title: String, value: String, alignment: HorizontalAlignment) -> some View {
        VStack(alignment: alignment, spacing: 4 * scale) {
            Text(title)
                .font(.system(size: 10 * scale, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(TransferPalette.textMuted)
            Text(value)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(TransferPalette.textPrimary)
        }
    }
}

private struct TransferStatusDotPill: View {
    let kind: TransferStatusKind
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 6 * scale) {
            Circle()
                .fill(kind.color)
                .frame(width: 6 * scale, height: 6 * scale)
            Text(kind.label.uppercased())
                .font(.system(size: 10 * scale, weight: .bold))
                .tracking(1)
                .foregroundStyle(kind.color)
        }
        .padding(.horizontal, 10 * scale)
        .padding(.vertical, 5 * scale)
        .background(Capsule().fill(kind.mutedColor))
    }
}

private struct TransferCompactFlow: View {
    let data: TransferConfirmationData
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 10 * scale) {
            endpoint(isSource: true)
                .frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: "arrow.right")
                .font(.system(size: 11 * scale, weight: .bold))
                .foregroundStyle(TransferPalette.textFaint)
            endpoint(isSource: false)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12 * scale)
        .background(
            RoundedRectangle(cornerRadius: 14 * scale)
                .fill(TransferPalette.chipBackground)
        )
    }

    @ViewBuilder
    private func endpoint(isSource: Bool) -> some View {
        let isBank = (data.direction == .deposit) == isSource
        HStack(spacing: 10 * scale) {
            AccountAvatar(
                kind: isBank ? .bank(data.bankInstitution) : .brokerage,
                scale: scale * 0.9
            )
            VStack(alignment: .leading, spacing: 1 * scale) {
                Text(isSource ? L10n.Transfer.fromLabel.uppercased() : L10n.Transfer.toLabel.uppercased())
                    .font(.system(size: 9 * scale, weight: .semibold))
                    .tracking(1)
                    .foregroundStyle(TransferPalette.textMuted)
                Text(isBank ? data.bankInstitution : L10n.Transfer.brokerageName)
                    .font(.system(size: 13 * scale, weight: .semibold))
                    .foregroundStyle(TransferPalette.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
    }
}

// MARK: - Failed receipt (accent stripe)

private struct TransferFailedReceipt: View {
    let data: TransferConfirmationData
    let scale: CGFloat
    let onDismiss: (() -> Void)?

    private var directionLabel: String {
        (data.direction == .deposit ? L10n.Transfer.depositBadge : L10n.Transfer.withdrawBadge).uppercased()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16 * scale) {
            HStack(spacing: 0) {
                Text(L10n.Transfer.failedHeader(directionLabel))
                    .font(.system(size: 11 * scale, weight: .bold))
                    .tracking(1.2)
                    .foregroundStyle(TransferPalette.failRed)
                Spacer()
                if let onDismiss {
                    Button(action: onDismiss) {
                        Image(systemName: "xmark")
                            .font(.system(size: 11 * scale, weight: .bold))
                            .foregroundStyle(TransferPalette.failRed)
                            .frame(width: 26 * scale, height: 26 * scale)
                            .background(Circle().fill(TransferPalette.failRedMuted))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.Transfer.closeAccessibility)
                }
            }

            Text(data.amount.formatted(.currency(code: data.currencyCode)))
                .font(.system(size: 32 * scale, weight: .bold))
                .foregroundStyle(TransferPalette.textPrimary)

            HStack(spacing: 14 * scale) {
                AccountAvatar(kind: .bank(data.bankInstitution), scale: scale)
                VStack(alignment: .leading, spacing: 2 * scale) {
                    Text(data.bankInstitution)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(TransferPalette.textPrimary)
                    Text(bankTypeLine)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(TransferPalette.textTertiary)
                }
                Spacer(minLength: 0)
                Text(L10n.Transfer.sourceLabel)
                    .font(.system(size: 10 * scale, weight: .semibold))
                    .tracking(1.2)
                    .foregroundStyle(TransferPalette.textMuted)
            }

            Rectangle()
                .fill(TransferPalette.hairline)
                .frame(height: 1)

            HStack(alignment: .top, spacing: 20 * scale) {
                metaColumn(
                    title: L10n.Transfer.submittedLabel,
                    value: data.createdAt.formatted(date: .abbreviated, time: .shortened),
                    color: TransferPalette.textPrimary
                )
                Spacer(minLength: 0)
                metaColumn(
                    title: L10n.Transfer.reasonLabel,
                    value: data.reason ?? L10n.Transfer.statusFailed,
                    color: TransferPalette.failRed
                )
            }
        }
        .padding(20 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GenUICardBackground(cornerRadius: 28 * scale))
    }

    private var bankTypeLine: String {
        let type = data.bankAccountType ?? ""
        return type.isEmpty
            ? "•••• \(data.bankMask)"
            : L10n.Transfer.bankTypeMaskFormat(type, data.bankMask)
    }

    private func metaColumn(title: String, value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(title)
                .font(.system(size: 10 * scale, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(TransferPalette.textMuted)
            Text(value)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(color)
        }
    }
}

// MARK: - Previews

private let previewDate = Calendar.current.date(
    from: DateComponents(year: 2026, month: 4, day: 24, hour: 10, minute: 42)
) ?? .now

#Preview("Queued · deposit") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferConfirmationCard(
            data: TransferConfirmationData(
                direction: .deposit,
                amount: 500,
                currencyCode: "USD",
                bankInstitution: "Chase",
                bankMask: "4821",
                bankAccountType: "Checking",
                status: "QUEUED",
                createdAt: previewDate,
                estimatedSettlement: "Apr 28, 2026",
                reason: nil
            )
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Complete · withdraw") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferConfirmationCard(
            data: TransferConfirmationData(
                direction: .withdraw,
                amount: 1200,
                currencyCode: "USD",
                bankInstitution: "Schwab Bank",
                bankMask: "9102",
                bankAccountType: "Savings",
                status: "COMPLETE",
                createdAt: previewDate,
                estimatedSettlement: "Apr 26, 2026",
                reason: nil
            )
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}

#Preview("Failed · deposit") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        TransferConfirmationCard(
            data: TransferConfirmationData(
                direction: .deposit,
                amount: 2500,
                currencyCode: "USD",
                bankInstitution: "Wells Fargo",
                bankMask: "0255",
                bankAccountType: "Checking",
                status: "FAILED",
                createdAt: previewDate,
                estimatedSettlement: nil,
                reason: "ACH returned"
            ),
            onDismiss: {}
        )
        .padding(20)
    }
    .preferredColorScheme(.dark)
}
