import SwiftUI

struct HomeTimeRangeSelector: View {
    let selected: TimeRange
    let scale: CGFloat
    let onSelect: (TimeRange) -> Void

    @GestureState private var dragLocation: CGFloat?
    @State private var totalWidth: CGFloat = 0

    private var isPressing: Bool { dragLocation != nil }

    private var activeRange: TimeRange {
        if let x = dragLocation, let range = rangeAt(x: x) {
            return range
        }
        return selected
    }

    private var itemWidth: CGFloat {
        let count = CGFloat(TimeRange.allCases.count)
        guard count > 0 else { return 0 }
        return totalWidth / count
    }

    private var indicatorOffsetX: CGFloat {
        guard let idx = TimeRange.allCases.firstIndex(of: activeRange) else { return 0 }
        return CGFloat(idx) * itemWidth
    }

    var body: some View {
        ZStack(alignment: .leading) {
            if totalWidth > 0 {
                Capsule()
                    .fill(.clear)
                    .modifier(SevinoGlass.chip)
                    .frame(width: itemWidth)
                    .scaleEffect(isPressing ? 1.12 : 1.0)
                    .offset(x: indicatorOffsetX)
                    .allowsHitTesting(false)
            }

            HStack(spacing: 0) {
                ForEach(TimeRange.allCases) { range in
                    Text(range.rawValue)
                        .font(.system(size: 13 * scale, weight: .medium))
                        .foregroundStyle(
                            range == activeRange
                                ? Color.sevinoSecondary
                                : Color.sevinoGreyContrast
                        )
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .padding(.vertical, 6 * scale)
                        .contentShape(.rect)
                        .accessibilityLabel(range.periodLabel)
                        .accessibilityAddTraits(.isButton)
                        .accessibilityAction {
                            onSelect(range)
                        }
                }
            }
        }
        .onGeometryChange(for: CGFloat.self) { geo in
            geo.size.width
        } action: { newValue in
            totalWidth = newValue
        }
        .gesture(
            DragGesture(minimumDistance: 0)
                .updating($dragLocation) { value, state, _ in
                    state = value.location.x
                }
                .onEnded { value in
                    guard let range = rangeAt(x: value.location.x) else { return }
                    onSelect(range)
                }
        )
        .animation(.spring(duration: 0.35, bounce: 0.2), value: indicatorOffsetX)
        .animation(.spring(duration: 0.25, bounce: 0.2), value: isPressing)
        .animation(.easeOut(duration: 0.2), value: activeRange)
    }

    private func rangeAt(x: CGFloat) -> TimeRange? {
        let cases = TimeRange.allCases
        guard !cases.isEmpty, totalWidth > 0, itemWidth > 0 else { return nil }
        let clamped = max(0, min(x, totalWidth - 0.001))
        let idx = Int(clamped / itemWidth)
        guard idx >= 0, idx < cases.count else { return nil }
        return cases[idx]
    }
}
