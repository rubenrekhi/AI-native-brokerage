import SwiftUI

struct PortfolioChartView: View {
    let points: [CGFloat]
    let scale: CGFloat
    @Binding var scrubValue: String?

    @State private var scrubIndex: Int?
    @State private var displayPoints: [CGFloat] = []

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width
            let height = geo.size.height

            ZStack(alignment: .bottom) {
                AnimatableChartFill(points: displayPoints, size: geo.size)
                    .fill(
                        LinearGradient(
                            colors: [Color.saturnPositive.opacity(0.3), Color.saturnPositive.opacity(0.02)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )

                AnimatableChartLine(points: displayPoints, size: geo.size)
                    .stroke(Color.saturnPositive, lineWidth: 2 * scale)

                if let idx = scrubIndex, idx < displayPoints.count, let label = scrubValue {
                    let step = width / CGFloat(displayPoints.count - 1)
                    let x = CGFloat(idx) * step
                    let y = height - (displayPoints[idx] * height)
                    let labelX = min(max(x, 40 * scale), width - 40 * scale)

                    Rectangle()
                        .fill(Color.saturnGreyContrast.opacity(0.5))
                        .frame(width: 1 * scale)
                        .position(x: x, y: height / 2)
                        .accessibilityHidden(true)

                    Circle()
                        .fill(Color.saturnPositive)
                        .frame(width: 8 * scale, height: 8 * scale)
                        .position(x: x, y: y)
                        .accessibilityHidden(true)

                    Text(label)
                        .font(.system(size: 12 * scale, weight: .semibold))
                        .foregroundStyle(Color.saturnSecondary)
                        .padding(.horizontal, 8 * scale)
                        .padding(.vertical, 4 * scale)
                        .modifier(SaturnGlass.nav)
                        .position(x: labelX, y: y - 20 * scale)
                }
            }
            .contentShape(.rect)
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        updateScrub(at: value.location.x, width: width)
                    }
                    .onEnded { _ in
                        scrubIndex = nil
                        scrubValue = nil
                    }
            )
        }
        .onChange(of: points) {
            withAnimation(.easeInOut(duration: 0.4)) {
                displayPoints = points
            }
        }
        .onAppear { displayPoints = points }
    }

    private func updateScrub(at x: CGFloat, width: CGFloat) {
        guard displayPoints.count > 1 else { return }
        let step = width / CGFloat(displayPoints.count - 1)
        let idx = min(max(Int((x / step).rounded()), 0), displayPoints.count - 1)
        scrubIndex = idx
        let dollarValue = 400 + displayPoints[idx] * 800
        scrubValue = Double(dollarValue).formatted(.currency(code: "USD"))
    }
}

/// A vector type that SwiftUI can interpolate for chart animation.
private struct AnimatableVector: VectorArithmetic {
    var values: [CGFloat]

    static var zero: AnimatableVector { AnimatableVector(values: []) }

    static func + (lhs: AnimatableVector, rhs: AnimatableVector) -> AnimatableVector {
        let count = max(lhs.values.count, rhs.values.count)
        var result = [CGFloat](repeating: 0, count: count)
        for i in 0..<count {
            let l = i < lhs.values.count ? lhs.values[i] : 0
            let r = i < rhs.values.count ? rhs.values[i] : 0
            result[i] = l + r
        }
        return AnimatableVector(values: result)
    }

    static func - (lhs: AnimatableVector, rhs: AnimatableVector) -> AnimatableVector {
        let count = max(lhs.values.count, rhs.values.count)
        var result = [CGFloat](repeating: 0, count: count)
        for i in 0..<count {
            let l = i < lhs.values.count ? lhs.values[i] : 0
            let r = i < rhs.values.count ? rhs.values[i] : 0
            result[i] = l - r
        }
        return AnimatableVector(values: result)
    }

    mutating func scale(by rhs: Double) {
        for i in values.indices {
            values[i] *= CGFloat(rhs)
        }
    }

    var magnitudeSquared: Double {
        values.reduce(0) { $0 + Double($1 * $1) }
    }
}

private struct AnimatableChartLine: Shape {
    var points: [CGFloat]
    var size: CGSize

    var animatableData: AnimatableVector {
        get { AnimatableVector(values: points) }
        set { points = newValue.values }
    }

    func path(in rect: CGRect) -> Path {
        guard points.count > 1 else { return Path() }
        let step = size.width / CGFloat(points.count - 1)

        return Path { path in
            for (index, point) in points.enumerated() {
                let x = CGFloat(index) * step
                let y = size.height - (point * size.height)
                if index == 0 {
                    path.move(to: CGPoint(x: x, y: y))
                } else {
                    path.addLine(to: CGPoint(x: x, y: y))
                }
            }
        }
    }
}

private struct AnimatableChartFill: Shape {
    var points: [CGFloat]
    var size: CGSize

    var animatableData: AnimatableVector {
        get { AnimatableVector(values: points) }
        set { points = newValue.values }
    }

    func path(in rect: CGRect) -> Path {
        guard points.count > 1 else { return Path() }
        let step = size.width / CGFloat(points.count - 1)

        return Path { path in
            path.move(to: CGPoint(x: 0, y: size.height))
            for (index, point) in points.enumerated() {
                let x = CGFloat(index) * step
                let y = size.height - (point * size.height)
                path.addLine(to: CGPoint(x: x, y: y))
            }
            path.addLine(to: CGPoint(x: size.width, y: size.height))
            path.closeSubpath()
        }
    }
}

#Preview {
    PortfolioChartView(
        points: (0..<40).map { _ in CGFloat.random(in: 0.1...0.9) },
        scale: 1,
        scrubValue: .constant(nil)
    )
    .frame(height: 160)
    .padding()
    .background(Color.saturnPrimary)
}
