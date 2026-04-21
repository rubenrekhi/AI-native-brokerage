import SwiftUI

struct AnimatedChartLine: View {
    let points: [CGFloat]
    let scale: CGFloat
    let height: CGFloat
    let progress: CGFloat

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height

            Path { path in
                for (i, point) in points.enumerated() {
                    let x = w * CGFloat(i) / CGFloat(points.count - 1)
                    let y = h * (1 - point)
                    if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                    else { path.addLine(to: CGPoint(x: x, y: y)) }
                }
                path.addLine(to: CGPoint(x: w, y: h))
                path.addLine(to: CGPoint(x: 0, y: h))
                path.closeSubpath()
            }
            .fill(
                LinearGradient(
                    colors: [Color.welcomeChart.opacity(0.3), Color.welcomeChart.opacity(0)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .mask(alignment: .leading) {
                Rectangle()
                    .frame(width: w * progress)
            }

            Path { path in
                for (i, point) in points.enumerated() {
                    let x = w * CGFloat(i) / CGFloat(points.count - 1)
                    let y = h * (1 - point)
                    if i == 0 { path.move(to: CGPoint(x: x, y: y)) }
                    else { path.addLine(to: CGPoint(x: x, y: y)) }
                }
            }
            .trim(from: 0, to: progress)
            .stroke(Color.welcomeChart, lineWidth: 1.5)
        }
        .frame(height: height * scale)
    }
}
