import SafariServices
import SwiftUI

enum DigestCardFormatting {
    static func monthDay(_ date: Date) -> String {
        monthDayFormatter.string(from: date)
    }

    static func dateTime(_ date: Date) -> String {
        dateTimeFormatter.string(from: date)
    }

    static func timeAgo(_ date: Date, relativeTo now: Date = .now) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: now)
    }

    private static let monthDayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("MMM d")
        return formatter
    }()

    private static let dateTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.setLocalizedDateFormatFromTemplate("MMM d, h:mm a")
        return formatter
    }()
}

struct PriceMoveCardBody: View {
    let symbol: String
    let name: String
    let prevClose: Decimal
    let current: Decimal
    let changeAbs: Decimal
    let changePct: Decimal
    let reason: String?
    let badgeText: String?
    let scale: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 18 * scale) {
            if let badgeText {
                DigestPill(text: badgeText, color: .sevinoInfo, scale: scale)
            }

            DigestTickerHeader(symbol: symbol, name: name, scale: scale)

            VStack(alignment: .leading, spacing: 8 * scale) {
                HStack(alignment: .firstTextBaseline, spacing: 8 * scale) {
                    Text(prevClose.asCurrency())
                        .font(.system(size: 17 * scale, weight: .medium))
                        .foregroundStyle(Color.sevinoPrimary.opacity(0.58))

                    Image(systemName: "arrow.right")
                        .font(.system(size: 14 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoPrimary.opacity(0.46))
                        .accessibilityHidden(true)

                    Text(current.asCurrency())
                        .font(.dmSerif(size: 42 * scale))
                        .foregroundStyle(Color.sevinoPrimary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                }

                HStack(spacing: 6 * scale) {
                    Image(systemName: changePct >= 0 ? "arrow.up.right" : "arrow.down.right")
                        .font(.system(size: 12 * scale, weight: .bold))
                        .foregroundStyle(changePct.digestSignedColor)
                        .accessibilityHidden(true)

                    Text("\(changeAbs.asSignedCurrency()) (\(changePct.asSignedPercent()))")
                        .font(.system(size: 16 * scale, weight: .semibold))
                        .foregroundStyle(changePct.digestSignedColor)
                }
            }

            if let reason, !reason.isEmpty {
                Text(reason)
                    .font(.dmSerifItalic(size: 20 * scale))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.76))
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)
        }
    }
}

struct DigestTickerHeader: View {
    let symbol: String
    let name: String
    let scale: CGFloat

    var body: some View {
        HStack(spacing: 10 * scale) {
            StockLogoView(ticker: symbol, size: 34 * scale)

            VStack(alignment: .leading, spacing: 2 * scale) {
                Text(symbol)
                    .font(.system(size: 18 * scale, weight: .bold))
                    .foregroundStyle(Color.sevinoPrimary)

                Text(name)
                    .font(.system(size: 13 * scale))
                    .foregroundStyle(Color.sevinoPrimary.opacity(0.62))
                    .lineLimit(1)
            }
        }
    }
}

struct DigestMetricChip: View {
    let label: String
    let value: String
    let color: Color?
    let scale: CGFloat

    init(label: String, value: String, color: Color? = nil, scale: CGFloat) {
        self.label = label
        self.value = value
        self.color = color
        self.scale = scale
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4 * scale) {
            Text(label)
                .font(.system(size: 11 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoPrimary.opacity(0.58))
                .textCase(.uppercase)

            Text(value)
                .font(.system(size: 16 * scale, weight: .semibold))
                .foregroundStyle(color ?? Color.sevinoPrimary)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
        }
        .padding(.horizontal, 12 * scale)
        .padding(.vertical, 10 * scale)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.sevinoPrimary.opacity(0.06), in: .rect(cornerRadius: 8 * scale))
    }
}

struct DigestInfoRow: View {
    let label: String
    let value: String
    let valueColor: Color?
    let scale: CGFloat

    init(label: String, value: String, valueColor: Color? = nil, scale: CGFloat) {
        self.label = label
        self.value = value
        self.valueColor = valueColor
        self.scale = scale
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10 * scale) {
            Text(label)
                .font(.system(size: 13 * scale))
                .foregroundStyle(Color.sevinoPrimary.opacity(0.6))
                .lineLimit(1)

            Spacer(minLength: 8 * scale)

            Text(value)
                .font(.system(size: 14 * scale, weight: .semibold))
                .foregroundStyle(valueColor ?? Color.sevinoPrimary)
                .multilineTextAlignment(.trailing)
                .minimumScaleFactor(0.78)
        }
        .padding(.vertical, 8 * scale)
    }
}

struct DigestPill: View {
    let text: String
    let color: Color
    let scale: CGFloat

    var body: some View {
        Text(text)
            .font(.system(size: 12 * scale, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 10 * scale)
            .padding(.vertical, 6 * scale)
            .background(color.opacity(0.12), in: .capsule)
    }
}

struct DigestSafariURL: Identifiable {
    let id = UUID()
    let url: URL
}

struct DigestSafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ uiViewController: SFSafariViewController, context: Context) {}
}

extension Decimal {
    var digestSignedColor: Color {
        if self > 0 { return .sevinoPositive }
        if self < 0 { return .sevinoNegative }
        return .sevinoGreyContrast
    }
}
