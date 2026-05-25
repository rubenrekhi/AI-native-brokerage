import SwiftUI

struct OnboardingBackgroundView: View {
    var body: some View {
        PastelMeshBackground(
            baseColor: .sevinoPrimary,
            blendMode: .plusLighter,
            gradientOpacity: 0.25
        )
    }
}

#Preview("Dark") {
    OnboardingBackgroundView()
        .preferredColorScheme(.dark)
}

#Preview("Light") {
    OnboardingBackgroundView()
        .preferredColorScheme(.light)
}
