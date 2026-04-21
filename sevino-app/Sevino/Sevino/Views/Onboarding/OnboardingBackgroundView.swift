import SwiftUI

struct OnboardingBackgroundView: View {
    var body: some View {
        ZStack {
            Image("onboarding_bg")
                .resizable()
                .aspectRatio(contentMode: .fill)
                .accessibilityHidden(true)

            LinearGradient(
                stops: [
                    .init(color: .welcomeOverlayTop, location: 0),
                    .init(color: .welcomeOverlayMid, location: 0.45),
                    .init(color: .welcomeOverlayBottom, location: 1),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        }
        .ignoresSafeArea()
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
