import SwiftUI

struct HomeBackgroundView: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.colorScheme) private var colorScheme
    @State private var phase: CGFloat = 0

    var body: some View {
        ZStack {
            Color.sevinoPrimary
                .ignoresSafeArea()

            if #available(iOS 18, *) {
                meshGradient
                    .ignoresSafeArea()
                    // plusLighter reveals the mesh on a black base (dark mode) but
                    // saturates to white on a near-white base (light mode). Fall
                    // back to normal compositing in light mode.
                    .blendMode(colorScheme == .dark ? .plusLighter : .normal)
                    .opacity(colorScheme == .dark ? 0.25 : 0.9)
            } else {
                LinearGradient(
                    stops: [
                        .init(color: Color.homeGradientLavender.opacity(0.85), location: 0),
                        .init(color: Color.sevinoPrimary, location: 0.18),
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
        let lavender = Color.homeGradientLavender
        let peach    = Color.homeGradientPeach
        let mint     = Color.homeGradientMint
        let sky      = Color.homeGradientSky
        let rose     = Color.homeGradientRose
        let mid      = Color.sevinoPrimary

        let points: [SIMD2<Float>] = [
            SIMD2(0.0, 0.0),
            SIMD2(Float(0.5 + 0.05 * phase), 0.0),
            SIMD2(1.0, 0.0),
            SIMD2(0.0, Float(0.35 - 0.04 * phase)),
            SIMD2(0.5, Float(0.45 + 0.04 * phase)),
            SIMD2(1.0, 0.4),
            SIMD2(0.0, 1.0),
            SIMD2(Float(0.5 - 0.04 * phase), 1.0),
            SIMD2(1.0, 1.0),
        ]
        let colors: [Color] = [
            lavender.opacity(0.9), peach.opacity(0.6), sky.opacity(0.8),
            mint.opacity(0.3),     rose.opacity(0.2),  mid,
            mid,                   mid,                mid,
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
