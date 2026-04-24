import Foundation

/// Pure functions for transforming onboarding UI data into backend-compatible formats.
enum OnboardingDataMapper {

    private static let isoFormatter = ISO8601DateFormatter()

    /// Current timestamp in ISO 8601 format.
    static func isoTimestamp() -> String {
        isoFormatter.string(from: .now)
    }

    /// Convert DOB from "MM-DD-YYYY" (UI format) to "YYYY-MM-DD" (ISO / backend format).
    static func formatDateOfBirth(_ dob: String) -> String {
        let parts = dob.split(separator: "-")
        guard parts.count == 3 else { return dob }
        return "\(parts[2])-\(parts[0])-\(parts[1])"
    }

    /// Split a full name into (firstName, lastName).
    /// "Riley Johnson" → ("Riley", "Johnson")
    /// "Riley" → ("Riley", "")
    /// "Riley James Johnson" → ("Riley", "James Johnson")
    static func splitLegalName(_ fullName: String) -> (firstName: String, lastName: String) {
        let parts = fullName.split(separator: " ", maxSplits: 1)
        let first = String(parts.first ?? "")
        let last = parts.count > 1 ? String(parts[1]) : ""
        return (first, last)
    }

    /// Normalize employment status for the backend.
    /// "Self-Employed" → "self_employed"
    /// "Employed" → "employed"
    static func normalizeEmploymentStatus(_ status: String) -> String {
        status.lowercased().replacingOccurrences(of: "-", with: "_")
    }

    /// Convert a normalized backend employment status back to the localized
    /// display label used by `AlpacaEmploymentView`. Unknown values pass through
    /// unchanged so we never lose the user's saved value.
    static func denormalizeEmploymentStatus(_ normalized: String) -> String {
        switch normalized {
        case "employed": return L10n.Onboarding.alpacaStatusEmployed
        case "self_employed": return L10n.Onboarding.alpacaStatusSelfEmployed
        case "unemployed": return L10n.Onboarding.alpacaStatusUnemployed
        case "student": return L10n.Onboarding.alpacaStatusStudent
        case "retired": return L10n.Onboarding.alpacaStatusRetired
        default: return normalized
        }
    }

    /// Map a funding source display label to Alpaca's accepted value.
    /// See: https://docs.alpaca.markets/reference/createaccount
    private static let fundingSourceMap: [String: String] = [
        "Employment income": "employment_income",
        "Savings": "savings",
        "Existing investments": "investments",
        "Business income": "business_income",
        "Family": "family",
        "Inheritance": "inheritance",
    ]

    private static let fundingSourceReverseMap: [String: String] = Dictionary(
        uniqueKeysWithValues: fundingSourceMap.map { ($1, $0) }
    )

    static func normalizeFundingSource(_ source: String) -> String {
        fundingSourceMap[source] ?? source.lowercased().replacingOccurrences(of: " ", with: "_")
    }

    /// Inverse of `normalizeFundingSource`. Used to hydrate the Funding Sources
    /// screen on resume so the pre-selected chips match the option labels.
    static func denormalizeFundingSource(_ normalized: String) -> String {
        fundingSourceReverseMap[normalized] ?? normalized
    }

    /// Build the attribution string from referral source + optional extra text.
    /// ("Friend", "John") → "Friend: John"
    /// ("TikTok", nil) → "TikTok"
    static func buildAttribution(source: String, extra: String?) -> String {
        if let extra, !extra.isEmpty {
            return "\(source): \(extra)"
        }
        return source
    }
}
