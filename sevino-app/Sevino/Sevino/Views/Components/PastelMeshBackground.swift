import SwiftUI

struct PastelMeshBackground: View {
    let baseColor: Color
    let blendMode: BlendMode
    let gradientOpacity: Double

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = 0

    var body: some View {
        ZStack {
            baseColor
                .ignoresSafeArea()

            if #available(iOS 18, *) {
                meshGradient
                    .ignoresSafeArea()
                    .blendMode(blendMode)
                    .opacity(gradientOpacity)
            } else {
                LinearGradient(
                    stops: [
                        .init(color: Color.sevinoGradientLavender.opacity(gradientOpacity), location: 0),
                        .init(color: baseColor, location: 0.18),
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
        let lavender = Color.sevinoGradientLavender
        let peach    = Color.sevinoGradientPeach
        let mint     = Color.sevinoGradientMint
        let sky      = Color.sevinoGradientSky
        let rose     = Color.sevinoGradientRose
        let mid      = baseColor

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
