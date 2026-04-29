import Foundation

/// Single document returned from GET /v1/settings/documents. `date` is an
/// ISO-8601 string (`YYYY-MM-DD`) from the upstream broker; `type` is the
/// broker's document category (e.g. "account_statement", "tax_1099").
struct DocumentDTO: Decodable, Identifiable, Equatable {
    let id: String
    let type: String
    let date: String
    let name: String?
}

/// Response from GET /v1/settings/documents.
struct DocumentListResponse: Decodable, Equatable {
    let documents: [DocumentDTO]
}

extension DocumentDTO {
    var displayTitle: String {
        if let name = name?.trimmingCharacters(in: .whitespacesAndNewlines),
           !name.isEmpty {
            return name
        }
        return Self.typeLabel(type)
    }

    var displayDate: String {
        Self.formatDate(date)
    }

    /// Humanizes broker document type slugs ("account_statement" → "Account statement")
    /// for rows that are missing a server-provided display name.
    static func typeLabel(_ type: String) -> String {
        let words = type.replacingOccurrences(of: "_", with: " ")
        guard let first = words.first else { return type }
        return first.uppercased() + words.dropFirst()
    }

    static func formatDate(_ raw: String) -> String {
        if let date = isoDayFormatter.date(from: raw) {
            return displayDayFormatter.string(from: date)
        }
        return raw
    }

    private static let isoDayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private static let displayDayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .long
        f.timeStyle = .none
        return f
    }()
}
