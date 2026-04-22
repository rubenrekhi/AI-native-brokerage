import SwiftUI

struct BouncePillButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.82 : 1.0)
            .opacity(configuration.isPressed ? 0.8 : 1.0)
            .animation(.spring(duration: 0.32, bounce: 0.6), value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == BouncePillButtonStyle {
    static var bouncePill: BouncePillButtonStyle { BouncePillButtonStyle() }
}
