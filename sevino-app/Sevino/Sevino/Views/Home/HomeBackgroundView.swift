import SwiftUI

struct HomeBackgroundView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = 0

    var body: some View {
        ZStack {
            Color.sevinoPrimary
                .ignoresSafeArea()

            if #available(iOS 18, *) {
                meshGradient
                    .ignoresSafeArea()
                    .blendMode(.plusLighter)
                    .opacity(0.9)
            } else {
                LinearGradient(
                    stops: [
                        .init(color: Color.sevinoAccent, location: 0),
                        .init(color: Color.sevinoPrimary, location: 0.2),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()
            }
        }
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.easeInOut(duration: 12).repeatForever(autoreverses: true)) {
                phase = 1
            }
        }
    }

    @available(iOS 18, *)
    private var meshGradient: some View {
        let warm = Color.sevinoAccent
        let mid = Color.sevinoPrimary
        let cool = Color.sevinoAccent.opacity(0.55)
        let points: [SIMD2<Float>] = [
            SIMD2(0.0, 0.0),
            SIMD2(Float(0.5 + 0.05 * phase), 0.0),
            SIMD2(1.0, 0.0),
            SIMD2(0.0, Float(0.45 - 0.05 * phase)),
            SIMD2(0.5, Float(0.55 + 0.05 * phase)),
            SIMD2(1.0, 0.5),
            SIMD2(0.0, 1.0),
            SIMD2(Float(0.5 - 0.04 * phase), 1.0),
            SIMD2(1.0, 1.0),
        ]
        let colors: [Color] = [
            warm, warm.opacity(0.7), cool,
            mid, warm.opacity(0.4), mid,
            mid, mid, mid,
        ]
        return MeshGradient(
            width: 3,
            height: 3,
            points: points,
            colors: colors,
            smoothsColors: true
        )
    }
}

#Preview("Dark") {
    HomeBackgroundView()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    HomeBackgroundView()
        .preferredColorScheme(.light)
}
