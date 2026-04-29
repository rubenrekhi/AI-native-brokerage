import SwiftUI

/// Avatar shown next to a transfer endpoint — a colored initial circle for banks,
/// a mint-tinted chart glyph for the brokerage side.
struct AccountAvatar: View {
    enum Kind: Equatable {
        case bank(String)
        case brokerage
    }

    let kind: Kind
    let scale: CGFloat

    var body: some View {
        switch kind {
        case .bank(let name):
            Text(String(name.first ?? "•").uppercased())
                .font(.system(size: 16 * scale, weight: .bold))
                .foregroundStyle(TransferPalette.textPrimary)
                .frame(width: 36 * scale, height: 36 * scale)
                .background(
                    Circle().fill(Self.color(for: name))
                )
        case .brokerage:
            Image(systemName: "chart.line.uptrend.xyaxis")
                .font(.system(size: 16 * scale, weight: .bold))
                .foregroundStyle(TransferPalette.depositGreen)
                .frame(width: 36 * scale, height: 36 * scale)
                .background(
                    RoundedRectangle(cornerRadius: 10 * scale)
                        .fill(TransferPalette.depositGreen.opacity(0.12))
                )
        }
    }

    /// Deterministic avatar color keyed off the institution name. Uses a small palette
    /// tuned for dark backgrounds so adjacent avatars don't collide.
    static func color(for name: String) -> Color {
        let palette: [Color] = [
            Color(red: 0.29, green: 0.55, blue: 0.95),
            Color(red: 0.65, green: 0.33, blue: 0.86),
            Color(red: 0.90, green: 0.32, blue: 0.32),
            Color(red: 0.20, green: 0.67, blue: 0.55),
            Color(red: 0.95, green: 0.50, blue: 0.20),
            Color(red: 0.37, green: 0.49, blue: 0.70),
        ]
        let hash = name.unicodeScalars.reduce(0) { $0 &+ Int($1.value) }
        return palette[abs(hash) % palette.count]
    }
}
