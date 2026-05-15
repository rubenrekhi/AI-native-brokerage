import SwiftUI

struct StatusPillView: View {
    let block: StatusBlock
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 8 * scale) {
            leadingIndicator
            Text(block.label)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
        .padding(.horizontal, 14 * scale)
        .padding(.vertical, 10 * scale)
        .background(GenUICardBackground(cornerRadius: .infinity)
            .clipShape(.capsule))
        .padding(.horizontal, 16 * scale)
        .animation(.easeOut(duration: 0.25), value: block.state)
    }

    @ViewBuilder
    private var leadingIndicator: some View {
        switch block.state {
        case .active:
            AnimatedDotsView(scale: scale)
        case .complete:
            Image(systemName: "checkmark")
                .font(.system(size: 12 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoPositive)
                .accessibilityHidden(true)
                .transition(.scale.combined(with: .opacity))
        case .failed:
            Image(systemName: "xmark")
                .font(.system(size: 12 * scale, weight: .bold))
                .foregroundStyle(Color.sevinoNegative)
                .accessibilityHidden(true)
                .transition(.scale.combined(with: .opacity))
        }
    }

    private var accessibilityDescription: String {
        switch block.state {
        case .active: "\(block.label), \(L10n.Chat.statusInProgress)"
        case .complete: "\(block.label), \(L10n.Chat.statusComplete)"
        case .failed: "\(block.label), \(L10n.Chat.statusFailed)"
        }
    }
}

private struct AnimatedDotsView: View {
    let scale: CGFloat

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: Bool = false

    var body: some View {
        HStack(spacing: 4 * scale) {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .fill(Color.sevinoSecondary)
                    .frame(width: 5 * scale, height: 5 * scale)
                    .opacity(reduceMotion ? 1.0 : dotOpacity(for: index))
            }
        }
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(
                .easeInOut(duration: 0.6)
                .repeatForever(autoreverses: true)
            ) {
                phase = true
            }
        }
    }

    private func dotOpacity(for index: Int) -> Double {
        let base = phase ? 1.0 : 0.3
        let inverted = phase ? 0.3 : 1.0
        switch index {
        case 0: return base
        case 1: return (base + inverted) / 2
        case 2: return inverted
        default: return base
        }
    }
}

#Preview("Active") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        StatusPillView(
            block: StatusBlock(blockId: "1", label: "Pulling data on TSLA", state: .active),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Complete") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        StatusPillView(
            block: StatusBlock(blockId: "1", label: "Found portfolio data", state: .complete),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}

#Preview("Failed") {
    ZStack {
        Color.sevinoPrimary.ignoresSafeArea()
        StatusPillView(
            block: StatusBlock(blockId: "1", label: "Failed to load data", state: .failed),
            scale: 1
        )
    }
    .preferredColorScheme(.dark)
}
