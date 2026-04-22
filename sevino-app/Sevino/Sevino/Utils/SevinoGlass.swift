import SwiftUI

enum SevinoGlass {
    static let containerSpacing: CGFloat = 40

    static let card = CardGlass()
    static let chip = ChipGlass()
    static let button = ButtonGlass()
    static let nav = NavGlass()
    static let navCircle = NavCircleGlass()
    static let navClear = NavClearGlass()
    static let navCircleClear = NavCircleClearGlass()

    static func tintedButton(tint: Color) -> TintedButtonGlass {
        TintedButtonGlass(tint: tint)
    }

    static func tintedButton(tint: Color, cornerRadius: CGFloat) -> TintedButtonGlass {
        TintedButtonGlass(tint: tint, cornerRadius: cornerRadius)
    }

    static func conditionalChip(isSelected: Bool) -> ConditionalChipGlass {
        ConditionalChipGlass(isSelected: isSelected)
    }
}

struct SevinoGlassContainer<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        if #available(iOS 26, *) {
            GlassEffectContainer(spacing: SevinoGlass.containerSpacing) {
                content
            }
        } else {
            content
        }
    }
}

struct CardGlass: ViewModifier {
    static let cornerRadius: CGFloat = 28

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
                    .regular.interactive(),
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

struct NavCircleGlass: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(.regular, in: .circle)
        } else {
            content
                .background(.ultraThinMaterial, in: Circle())
        }
    }
}

struct NavClearGlass: ViewModifier {
    static let cornerRadius: CGFloat = 16

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(.clear.interactive(), in: .rect(cornerRadius: Self.cornerRadius))
        } else {
            content
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: Self.cornerRadius)
                )
        }
    }
}

struct NavCircleClearGlass: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(.clear.interactive(), in: .circle)
        } else {
            content
                .background(.ultraThinMaterial, in: Circle())
        }
    }
}

struct GlassMorphID: ViewModifier {
    let id: String
    let namespace: Namespace.ID

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content.glassEffectID(id, in: namespace)
        } else {
            content
        }
    }
}

struct ConditionalChipGlass: ViewModifier {
    let isSelected: Bool

    func body(content: Content) -> some View {
        if isSelected {
            content.modifier(SevinoGlass.chip)
        } else {
            content
        }
    }
}

struct TintedButtonGlass: ViewModifier {
    static let tintOpacity: CGFloat = 0.55

    let tint: Color
    var cornerRadius: CGFloat = CardGlass.cornerRadius

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .glassEffect(
                    .regular.tint(tint.opacity(Self.tintOpacity)).interactive(),
                    in: .rect(cornerRadius: cornerRadius)
                )
        } else {
            content
                .background(
                    tint.opacity(0.25),
                    in: RoundedRectangle(cornerRadius: cornerRadius)
                )
                .background(
                    .ultraThinMaterial,
                    in: RoundedRectangle(cornerRadius: cornerRadius)
                )
        }
    }
}
