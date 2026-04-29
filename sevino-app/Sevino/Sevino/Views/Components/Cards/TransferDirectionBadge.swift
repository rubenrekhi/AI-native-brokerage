import SwiftUI

/// Small pill that shows the direction of a transfer (deposit / withdraw). Shared
/// between `TransferCard` (setup) and `TransferConfirmationCard` (receipt).
struct TransferDirectionBadge: View {
    let direction: TransferDirection
    let scale: CGFloat

    private var color: Color {
        direction == .deposit ? TransferPalette.depositGreen : TransferPalette.withdrawAmber
    }
    private var background: Color {
        direction == .deposit ? TransferPalette.depositGreenMuted : TransferPalette.withdrawAmberMuted
    }
    private var icon: String {
        direction == .deposit ? "arrow.down" : "arrow.up"
    }
    private var label: String {
        direction == .deposit ? L10n.Transfer.depositBadge : L10n.Transfer.withdrawBadge
    }

    var body: some View {
        HStack(spacing: 6 * scale) {
            Image(systemName: icon)
                .font(.system(size: 10 * scale, weight: .bold))
            Text(label)
                .font(.system(size: 11 * scale, weight: .bold))
                .tracking(0.5)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 10 * scale)
        .padding(.vertical, 5 * scale)
        .background(
            RoundedRectangle(cornerRadius: 7 * scale)
                .fill(background)
        )
    }
}
