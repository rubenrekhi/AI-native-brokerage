import SwiftUI

/// Full-width green button that requires a sustained long press to fire its action.
///
/// A fill animation advances across the button over `holdDuration` seconds. If the user
/// lifts before the fill completes, the animation resets. When the press completes, a
/// success haptic plays, a brief scale pulse + confetti burst celebrate the confirmation,
/// and `action` is invoked.
struct HoldToConfirmButton: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let title: String
    var isEnabled: Bool = true
    var scale: CGFloat = 1
    var accessibilityHint: String = L10n.TradeExecution.holdToConfirmA11yHint
    let action: () -> Void

    @State private var progress: Double = 0
    @State private var pulse: CGFloat = 1
    @State private var fireCount = 0

    private static let holdDuration: Double = 2.0
    private static let cornerRadius: CGFloat = 14
    private static let height: CGFloat = 38

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: Self.cornerRadius * scale)
                .fill(Color.sevinoPositive.opacity(0.45))

            GeometryReader { geo in
                RoundedRectangle(cornerRadius: Self.cornerRadius * scale)
                    .fill(Color.sevinoPositive)
                    .frame(width: max(0, geo.size.width * progress))
            }
            .allowsHitTesting(false)

            Text(title)
                .font(.body.weight(.semibold))
                .foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .frame(height: Self.height * scale)
        .contentShape(.rect(cornerRadius: Self.cornerRadius * scale))
        .scaleEffect(pulse)
        .overlay {
            ConfettiBurst(trigger: fireCount)
                .allowsHitTesting(false)
        }
        .opacity(isEnabled ? 1 : 0.5)
        .onLongPressGesture(
            minimumDuration: Self.holdDuration,
            maximumDistance: 60,
            perform: {
                fireCount += 1
                if !reduceMotion {
                    withAnimation(.easeOut(duration: 0.14)) { pulse = 0.96 }
                    withAnimation(.spring(duration: 0.35, bounce: 0.15).delay(0.14)) { pulse = 1 }
                }
                action()
            },
            onPressingChanged: { pressing in
                if pressing {
                    withAnimation(.linear(duration: Self.holdDuration)) {
                        progress = 1
                    }
                } else {
                    withAnimation(.easeOut(duration: 0.25)) {
                        progress = 0
                    }
                }
            }
        )
        .disabled(!isEnabled)
        .sensoryFeedback(.success, trigger: fireCount)
        .accessibilityLabel(title)
        .accessibilityHint(accessibilityHint)
        .accessibilityAddTraits(.isButton)
    }
}

// MARK: - Confetti

private struct ConfettiBurst: View {
    let trigger: Int

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var bursts: [Burst] = []

    struct Burst: Identifiable {
        let id = UUID()
        let particles: [Particle]
    }

    struct Particle: Identifiable {
        let id = UUID()
        let angle: Double
        let distance: CGFloat
        let color: Color
        let size: CGFloat
        let rotation: Double
    }

    var body: some View {
        ZStack {
            ForEach(bursts) { burst in
                ConfettiLayer(particles: burst.particles)
            }
        }
        .onChange(of: trigger) { _, newValue in
            guard newValue > 0, !reduceMotion else { return }
            let burst = Burst(particles: Self.makeParticles())
            bursts.append(burst)
            Task {
                try? await Task.sleep(for: .milliseconds(1100))
                bursts.removeAll { $0.id == burst.id }
            }
        }
    }

    private static let palette: [Color] = [
        .sevinoPositive, .sevinoInfo, .sevinoAccent,
        .confettiYellow, .confettiPink, .confettiOrange
    ]

    private static func makeParticles() -> [Particle] {
        (0..<22).map { _ in
            Particle(
                angle: .random(in: 0...(2 * .pi)),
                distance: .random(in: 70...140),
                color: palette.randomElement() ?? .sevinoPositive,
                size: .random(in: 5...9),
                rotation: .random(in: -270...270)
            )
        }
    }
}

private struct ConfettiLayer: View {
    let particles: [ConfettiBurst.Particle]
    @State private var progress: Double = 0

    var body: some View {
        ZStack {
            ForEach(particles) { p in
                RoundedRectangle(cornerRadius: 1)
                    .fill(p.color)
                    .frame(width: p.size, height: p.size * 0.45)
                    .rotationEffect(.degrees(p.rotation * progress))
                    .offset(
                        x: cos(p.angle) * p.distance * progress,
                        y: sin(p.angle) * p.distance * progress + (progress * progress * 50)
                    )
                    .opacity(1 - progress)
            }
        }
        .onAppear {
            withAnimation(.easeOut(duration: 0.9)) {
                progress = 1
            }
        }
    }
}

#Preview {
    VStack(spacing: 20) {
        HoldToConfirmButton(title: L10n.TradeExecution.holdToConfirm) {}
        HoldToConfirmButton(title: L10n.TradeExecution.holdToConfirm, isEnabled: false) {}
    }
    .padding()
    .background(Color.sevinoPrimary)
}
