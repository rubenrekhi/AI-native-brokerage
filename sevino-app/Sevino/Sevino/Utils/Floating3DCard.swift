import SwiftUI

/// Tilts a card in 3D toward the touched quadrant — the daisyUI "hover 3D"
/// effect adapted for touch. The card surface is divided into a 3×3 grid; a
/// touch in any of the 8 outer cells snaps the card to a fixed tilt direction
/// (10° around the matching axis), drives a shine highlight to the
/// corresponding edge or corner, and offsets a soft shadow opposite the tilt.
/// Releasing springs the card back to rest with a bouncy curve.
///
/// Decorative only — does not invoke an action. The press gesture is attached
/// as a `simultaneousGesture` so child `Button`s still receive taps, and the
/// whole card is collapsed into a single accessibility element.
///
/// Note on iOS 26 Liquid Glass: glass-effect views are hoisted out of the
/// parent modifier stack, so applying `rotation3DEffect` to a view that
/// already has `SevinoGlass.card` may not rotate the glass refraction. Verify
/// the tilt visibly affects the glass surface on iOS 26 before relying on it.
struct Floating3DCardModifier: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var size: CGSize = .zero
    @State private var zone: Zone? = nil

    enum Zone: CaseIterable {
        case topLeft, top, topRight
        case left, right
        case bottomLeft, bottom, bottomRight

        /// Axis vector `(x, y)` for `rotate3d(x, y, 0, 10deg)`. Mirrors the
        /// daisyUI mapping (e.g. top-left tilts around `(-1, 1)`).
        var axis: (x: Double, y: Double) {
            switch self {
            case .topLeft:     (-1, 1)
            case .top:         (-1, 0)
            case .topRight:    (-1, -1)
            case .left:        (0, 1)
            case .right:       (0, -1)
            case .bottomLeft:  (1, 1)
            case .bottom:      (1, 0)
            case .bottomRight: (1, -1)
            }
        }

        /// Where the radial shine settles, in `UnitPoint` space.
        var shineCenter: UnitPoint {
            switch self {
            case .topLeft:     UnitPoint(x: 0,   y: 0)
            case .top:         UnitPoint(x: 0.5, y: 0)
            case .topRight:    UnitPoint(x: 1,   y: 0)
            case .left:        UnitPoint(x: 0,   y: 0.5)
            case .right:       UnitPoint(x: 1,   y: 0.5)
            case .bottomLeft:  UnitPoint(x: 0,   y: 1)
            case .bottom:      UnitPoint(x: 0.5, y: 1)
            case .bottomRight: UnitPoint(x: 1,   y: 1)
            }
        }

        /// Shadow offset in points, opposite to the touched corner.
        var shadowOffset: CGSize {
            switch self {
            case .topLeft:     CGSize(width: -4, height: -4)
            case .top:         CGSize(width:  0, height: -4)
            case .topRight:    CGSize(width:  4, height: -4)
            case .left:        CGSize(width: -4, height:  0)
            case .right:       CGSize(width:  4, height:  0)
            case .bottomLeft:  CGSize(width: -4, height:  4)
            case .bottom:      CGSize(width:  0, height:  4)
            case .bottomRight: CGSize(width:  4, height:  4)
            }
        }
    }

    func body(content: Content) -> some View {
        content
            .background(sizeReader)
            .overlay(shineOverlay)
            .scaleEffect(zone != nil ? 1.02 : 1.0, anchor: .center)
            .rotation3DEffect(
                .degrees(zone != nil ? 5 : 0),
                axis: (x: zone?.axis.x ?? 1, y: zone?.axis.y ?? 0, z: 0),
                anchor: .center,
                perspective: 0.4
            )
            .shadow(
                color: Color.sevinoShadow.opacity(zone != nil ? 0.24 : 0.16),
                radius: zone != nil ? 18 : 14,
                x: zone?.shadowOffset.width ?? 0,
                y: 10 + (zone?.shadowOffset.height ?? 0)
            )
            .animation(.spring(duration: 0.5, bounce: 0.35), value: zone)
            .simultaneousGesture(tiltGesture)
            .accessibilityElement(children: .combine)
    }

    private var sizeReader: some View {
        GeometryReader { proxy in
            Color.clear
                .onAppear { size = proxy.size }
                .onChange(of: proxy.size) { _, newSize in size = newSize }
        }
    }

    @ViewBuilder
    private var shineOverlay: some View {
        if let zone {
            RadialGradient(
                colors: [Color.white.opacity(0.14), Color.white.opacity(0)],
                center: zone.shineCenter,
                startRadius: 0,
                endRadius: max(size.width, size.height) * 0.5
            )
            .blendMode(.plusLighter)
            .clipShape(RoundedRectangle(cornerRadius: CardGlass.cornerRadius))
            .allowsHitTesting(false)
            .transition(.opacity)
        }
    }

    private var tiltGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                guard !reduceMotion else { return }
                zone = Self.zone(for: value.location, in: size)
            }
            .onEnded { _ in
                zone = nil
            }
    }

    /// Maps a touch location to one of the 8 outer tilt zones, or `nil` if
    /// the touch is in the center cell of the 3×3 grid (no tilt). Pure —
    /// extracted for testability.
    static func zone(for location: CGPoint, in size: CGSize) -> Zone? {
        guard size.width > 0, size.height > 0 else { return nil }
        let col = min(2, max(0, Int((location.x / size.width) * 3)))
        let row = min(2, max(0, Int((location.y / size.height) * 3)))
        switch (row, col) {
        case (0, 0): return .topLeft
        case (0, 1): return .top
        case (0, 2): return .topRight
        case (1, 0): return .left
        case (1, 1): return nil
        case (1, 2): return .right
        case (2, 0): return .bottomLeft
        case (2, 1): return .bottom
        case (2, 2): return .bottomRight
        default:     return nil
        }
    }
}

extension View {
    /// Applies the daisyUI-style "hover 3D" interaction adapted for touch:
    /// the card snaps to one of 8 fixed tilt directions based on the touch
    /// quadrant, with a shine highlight, offset shadow, and a bouncy spring
    /// release. Decorative only — does not invoke an action.
    func floating3DCard() -> some View {
        modifier(Floating3DCardModifier())
    }
}

#Preview("Floating 3D card") {
    ZStack {
        Color.sevinoSettingsBg.ignoresSafeArea()

        VStack(alignment: .leading, spacing: 12) {
            Text("Make things float in air")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color.sevinoSecondary)
            Text("Press different corners to tilt the card.")
                .font(.system(size: 13))
                .foregroundStyle(Color.sevinoGreyContrast)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .modifier(SevinoGlass.card)
        .floating3DCard()
        .padding(.horizontal, 24)
    }
    .preferredColorScheme(.dark)
}
