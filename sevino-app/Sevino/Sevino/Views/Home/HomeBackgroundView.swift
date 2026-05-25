import SwiftUI

struct HomeBackgroundView: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        PastelMeshBackground(
            baseColor: .sevinoPrimary,
            blendMode: colorScheme == .dark ? .plusLighter : .normal,
            gradientOpacity: colorScheme == .dark ? 0.25 : 0.9
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
