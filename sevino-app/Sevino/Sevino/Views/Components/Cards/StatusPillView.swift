import SwiftUI

/**
 Inline progress pill for `StatusBlock` (SEV-508 / C4.2).

 Renders the muted "Searching the web" / "Fetching price" pills the agent
 streams alongside other blocks. The runtime emits a `StatusBlock` with
 `state == .active` and later flips it to `.complete` or `.failed` via a
 single `block_data` patch — the icon swap and chrome shift cross-fade
 because the pill applies `.animation(value: block.state)` and each icon
 branch declares its own `.transition`.
 */
struct StatusPillView: View {
    let block: StatusBlock

    private static let iconTransition: AnyTransition =
        .scale.combined(with: .opacity)

    var body: some View {
        HStack(spacing: 6) {
            icon
                .frame(width: 18, height: 14)

            Text(block.label)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color.sevinoGreyContrast)
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Capsule().fill(backgroundColor))
        .overlay(Capsule().strokeBorder(borderColor, lineWidth: 0.5))
        .animation(.easeInOut(duration: 0.25), value: block.state)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    @ViewBuilder
    private var icon: some View {
        switch block.state {
        case .active:
            ActivityDots()
                .transition(Self.iconTransition)
        case .complete:
            Image(systemName: "checkmark")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(Color.sevinoPositive)
                .transition(Self.iconTransition)
        case .failed:
            Image(systemName: "xmark")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(Color.sevinoNegative)
                .transition(Self.iconTransition)
        }
    }

    private var backgroundColor: Color {
        switch block.state {
        case .active: Color.sevinoGreyAccent.opacity(0.25)
        case .complete: Color.sevinoPositive.opacity(0.12)
        case .failed: Color.sevinoNegative.opacity(0.12)
        }
    }

    private var borderColor: Color {
        switch block.state {
        case .active: Color.sevinoGreyAccent.opacity(0.4)
        case .complete: Color.sevinoPositive.opacity(0.3)
        case .failed: Color.sevinoNegative.opacity(0.3)
        }
    }

    private var accessibilityText: String {
        switch block.state {
        case .active: L10n.Chat.statusActiveAccessibility(block.label)
        case .complete: L10n.Chat.statusCompleteAccessibility(block.label)
        case .failed: L10n.Chat.statusFailedAccessibility(block.label)
        }
    }
}

/// Three pulsing dots — each phased a fraction apart so the animation
/// reads left-to-right.
private struct ActivityDots: View {
    @State private var pulsing = false

    private static let dotSize: CGFloat = 4
    private static let dotCount = 3
    private static let cycle: Double = 0.6
    private static let phaseStep: Double = 0.18

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<Self.dotCount) { index in
                Circle()
                    .fill(Color.sevinoGreyContrast)
                    .frame(width: Self.dotSize, height: Self.dotSize)
                    .opacity(pulsing ? 1.0 : 0.3)
                    .animation(
                        .easeInOut(duration: Self.cycle)
                            .repeatForever(autoreverses: true)
                            .delay(Self.phaseStep * Double(index)),
                        value: pulsing
                    )
            }
        }
        .onAppear { pulsing = true }
    }
}

#Preview("All states") {
    VStack(alignment: .leading, spacing: 12) {
        StatusPillView(block: StatusBlock(
            blockId: "1",
            label: "Searching the web",
            state: .active
        ))
        StatusPillView(block: StatusBlock(
            blockId: "2",
            label: "Fetched AMD price",
            state: .complete
        ))
        StatusPillView(block: StatusBlock(
            blockId: "3",
            label: "Couldn't reach Alpaca",
            state: .failed
        ))
    }
    .padding()
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(Color.sevinoPrimary)
}

#Preview("Live transition") {
    StatusPillTransitionPreview()
        .padding()
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.sevinoPrimary)
}

private struct StatusPillTransitionPreview: View {
    @State private var state: StatusState = .active

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            StatusPillView(block: StatusBlock(
                blockId: "preview",
                label: "Fetching AMD price",
                state: state
            ))
            HStack {
                Button("Active") { state = .active }
                Button("Complete") { state = .complete }
                Button("Failed") { state = .failed }
            }
            .buttonStyle(.bordered)
        }
    }
}
