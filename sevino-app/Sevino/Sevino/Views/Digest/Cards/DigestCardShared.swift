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

extension Decimal {
    var digestSignedColor: Color {
        if self > 0 { return .sevinoPositive }
        if self < 0 { return .sevinoNegative }
        return .sevinoGreyContrast
    }
}
