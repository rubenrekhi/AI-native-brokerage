import SwiftUI

struct OnboardingProgressBar: View {
    let currentStep: Int
    let totalSteps: Int
    let scale: CGFloat

    private var progress: CGFloat {
        CGFloat(currentStep) / CGFloat(totalSteps)
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.onboardingProgressTrack)

                Capsule()
                    .fill(Color.onboardingProgressFill)
                    .frame(width: max(geo.size.width * progress, geo.size.height))
                    .animation(.easeInOut(duration: 0.3), value: currentStep)
            }
        }
        .frame(height: 4 * scale)
        .accessibilityValue("\(currentStep) of \(totalSteps)")
    }
}
