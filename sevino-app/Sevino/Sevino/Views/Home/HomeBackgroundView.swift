import SwiftUI

struct HomeBackgroundView: View {
    var body: some View {
        LinearGradient(
            stops: [
                .init(color: Color.saturnAccent, location: 0),
                .init(color: Color.saturnPrimary, location: 0.2),
            ],
            startPoint: .top,
            endPoint: .bottom
        )
        .ignoresSafeArea()
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
