import SwiftUI

struct HomeTimeRangeSelector: View {
    let selected: TimeRange
    let scale: CGFloat
    let onSelect: (TimeRange) -> Void

    @Namespace private var indicator
    @GestureState private var dragLocation: CGFloat?
    @State private var totalWidth: CGFloat = 0

    private var isDragging: Bool { dragLocation != nil }

    var body: some View {
        HStack(spacing: 0) {
            ForEach(TimeRange.allCases) { range in
                Text(range.rawValue)
                    .font(.system(size: 13 * scale, weight: .medium))
                    .foregroundStyle(
                        range == activeRange
                            ? Color.sevinoSecondary
                            : Color.sevinoGreyContrast
                    )
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6 * scale)
                    .background {
                        if range == activeRange {
                            Capsule()
                                .fill(.clear)
                                .modifier(SevinoGlass.chip)
                                .scaleEffect(isDragging ? 1.25 : 1.0)
                                .matchedGeometryEffect(id: "timeIndicator", in: indicator)
                        }
                    }
                    .contentShape(.rect)
                    .onTapGesture {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                            onSelect(range)
                        }
                    }
                    .accessibilityAddTraits(.isButton)
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
                    if let range = rangeAt(x: value.location.x) {
                        withAnimation(.spring(duration: 0.3, bounce: 0.15)) {
                            onSelect(range)
                        }
                    }
                }
        )
        .animation(.spring(duration: 0.3, bounce: 0.15), value: activeRange)
        .animation(.spring(duration: 0.25, bounce: 0.2), value: isDragging)
    }

    private var activeRange: TimeRange {
        if let x = dragLocation, let range = rangeAt(x: x) {
            return range
        }
        return selected
    }

    private func rangeAt(x: CGFloat) -> TimeRange? {
        let cases = TimeRange.allCases
        guard !cases.isEmpty, totalWidth > 0 else { return nil }
        let itemWidth = totalWidth / CGFloat(cases.count)
        let idx = Int(x / itemWidth)
        guard idx >= 0, idx < cases.count else { return nil }
        return cases[idx]
    }
}
