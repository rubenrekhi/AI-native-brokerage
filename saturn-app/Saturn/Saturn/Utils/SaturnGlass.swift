import SwiftUI

enum SaturnGlass {
    static let card = CardGlass()
    static let chip = ChipGlass()
    static let button = ButtonGlass()
    static let nav = NavGlass()

    static func tintedButton(tint: Color) -> TintedButtonGlass {
        TintedButtonGlass(tint: tint)
    }
}

struct SaturnGlassContainer<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        if #available(iOS 26, *) {
            GlassEffectContainer {
                content
            }
        } else {
            content
        }
    }
}

struct CardGlass: ViewModifier {
    static let cornerRadius: CGFloat = 20

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(.regular, in: .rect(cornerRadius: Self.cornerRadius))
        } else {
            content
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: Self.cornerRadius)
                )
        }
    }
}

struct ChipGlass: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(.regular.interactive(), in: .capsule)
        } else {
            content
                .background(.ultraThinMaterial, in: Capsule())
        }
    }
}

struct ButtonGlass: ViewModifier {
    static let cornerRadius: CGFloat = 12

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(
                    .regular.tint(Color.saturnAccent).interactive(),
                    in: .rect(cornerRadius: Self.cornerRadius)
                )
        } else {
            content
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: Self.cornerRadius)
                )
        }
    }
}

struct NavGlass: ViewModifier {
    static let cornerRadius: CGFloat = 16

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(.regular, in: .rect(cornerRadius: Self.cornerRadius))
        } else {
            content
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: Self.cornerRadius)
                )
        }
    }
}

struct TintedButtonGlass: ViewModifier {
    let tint: Color

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(
                    .regular.tint(tint).interactive(),
                    in: .rect(cornerRadius: CardGlass.cornerRadius)
                )
        } else {
            content
                .background(
                    tint.opacity(0.25),
                    in: RoundedRectangle(cornerRadius: CardGlass.cornerRadius)
                )
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: CardGlass.cornerRadius)
                )
        }
    }
}
