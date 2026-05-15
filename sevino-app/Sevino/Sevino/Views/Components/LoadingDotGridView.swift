import SwiftUI

/// Animated grid of dots whose sizes gradient vertically and reverse over time.
/// Top dots start small / bottom large, then the gradient flips upward in a
/// smooth loop. Designed as a subtle background layer behind the loading logo.
struct LoadingDotGridView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var startDate = Date.now

    private let columns = 11
    private let dotSize: CGFloat = 6
    /// Full cycle (bottom-big → top-big → bottom-big) takes 2× this value.
    private let halfCycle: Double = 3.0

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion)) { timeline in
            Canvas { context, size in
                let elapsed = timeline.date.timeIntervalSince(startDate)
                let t = elapsed / (halfCycle * 2)
                // Smooth ease-in-out oscillation between 0 and 1.
                let phase = CGFloat((1 - cos(t * .pi * 2)) / 2)

                let hSpacing = size.width / CGFloat(columns)
                let rows = max(Int(size.height / hSpacing) + 1, 1)
                let vSpacing = size.height / CGFloat(rows)

                for row in 0...rows {
                    for col in 0..<columns {
                        let ny = CGFloat(row) / CGFloat(rows)

                        // Size gradient: lerp between bottom-big and top-big states.
                        let scaleA = 0.2 + 0.8 * ny
                        let scaleB = 0.2 + 0.8 * (1 - ny)
                        let s = dotSize * (scaleA + (scaleB - scaleA) * phase)

                        // Opacity follows the same gradient.
                        let opA = 0.08 + 0.25 * ny
                        let opB = 0.08 + 0.25 * (1 - ny)
                        let opacity = opA + (opB - opA) * phase

                        let x = hSpacing * (CGFloat(col) + 0.5)
                        let y = vSpacing * (CGFloat(row) + 0.5)
                        let rect = CGRect(x: x - s / 2, y: y - s / 2, width: s, height: s)

                        context.fill(
                            Circle().path(in: rect),
                            with: .color(Color.welcomeText.opacity(opacity))
                        )
                    }
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

#Preview {
    ZStack {
        Color.black.ignoresSafeArea()
        LoadingDotGridView()
    }
}
