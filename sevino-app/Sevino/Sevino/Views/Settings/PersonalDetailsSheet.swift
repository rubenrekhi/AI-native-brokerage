import SwiftUI

/// Read-only popup card that displays the user's KYC identity details — name,
/// date of birth, SSN (masked by default with an eye toggle), and citizenship.
/// These fields are immutable post-onboarding, so the popup has no Save action.
struct PersonalDetailsSheet: View {
    let firstName: String?
    let middleName: String?
    let lastName: String?
    let dateOfBirth: String?
    let countryOfCitizenship: String?
    /// Last four digits of the SSN. The full SSN is never stored client- or
    /// server-side, so the row only ever displays `•••-••-NNNN`.
    let taxIdLast4: String?

    @Environment(\.textSizeMultiplier) private var textMultiplier
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    var body: some View {
        SettingsEditPopup(
            title: L10n.Settings.personalDetailsTitle,
            scale: scale,
            saveAction: nil
        ) {
            VStack(alignment: .leading, spacing: 16 * scale) {
                row(label: L10n.Settings.personalDetailsFirstName, value: firstName)
                if let middle = middleName?.trimmingCharacters(in: .whitespaces), !middle.isEmpty {
                    row(label: L10n.Settings.personalDetailsMiddleName, value: middle)
                }
                row(label: L10n.Settings.personalDetailsLastName, value: lastName)
                row(label: L10n.Settings.personalDetailsDateOfBirth, value: formattedDateOfBirth)
                row(label: L10n.Settings.personalDetailsSsn, value: maskedSSN)
                row(label: L10n.Settings.personalDetailsCitizenship, value: formattedCitizenship)
            }
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
    }

    private func row(label: String, value: String?) -> some View {
        let displayValue = value?.trimmingCharacters(in: .whitespaces).nilIfEmpty
            ?? L10n.Settings.missingValuePlaceholder
        return SettingsEditPopupSection(label: label, scale: scale) {
            Text(displayValue)
                .font(.system(size: 16 * scale))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 4 * scale)
                .textSelection(.enabled)
        }
    }

    private var maskedSSN: String? { Self.maskedSSN(forLast4: taxIdLast4) }
    private var formattedDateOfBirth: String? { Self.formattedDateOfBirth(dateOfBirth) }
    private var formattedCitizenship: String? { Self.countryName(forCode: countryOfCitizenship) }

    /// Always renders as `•••-••-NNNN` from the stored last-4. Returns `nil`
    /// when last-4 isn't available so the row falls back to the standard
    /// missing-value placeholder.
    static func maskedSSN(forLast4 last4: String?) -> String? {
        guard
            let trimmed = last4?.trimmingCharacters(in: .whitespaces),
            trimmed.count == 4
        else { return nil }
        return "•••-••-\(trimmed)"
    }

    static func formattedDateOfBirth(_ raw: String?) -> String? {
        guard
            let trimmed = raw?.trimmingCharacters(in: .whitespaces),
            !trimmed.isEmpty
        else { return raw }
        guard let date = dateOfBirthInputFormatter.date(from: trimmed) else {
            return raw
        }
        return dateOfBirthOutputFormatter.string(from: date)
    }

    private static let dateOfBirthInputFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    /// Renders in UTC to match the input formatter — a birth date is a
    /// calendar day, not an instant, so parsing and formatting must agree on
    /// timezone. Otherwise `1992-04-15` parsed as UTC midnight renders as
    /// April 14 in any negative-UTC zone.
    private static let dateOfBirthOutputFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .long
        f.timeStyle = .none
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    /// Maps an ISO 3166-1 alpha-3 country code (`USA`) to its localized name
    /// (`United States`). Falls back to the raw code if no mapping is known.
    static func countryName(forCode code: String?) -> String? {
        guard
            let trimmed = code?.trimmingCharacters(in: .whitespaces).uppercased(),
            !trimmed.isEmpty
        else { return nil }
        let alpha2 = alpha3ToAlpha2[trimmed] ?? (trimmed.count == 2 ? trimmed : nil)
        if let alpha2, let name = Locale.current.localizedString(forRegionCode: alpha2) {
            return name
        }
        return trimmed
    }

    private static let alpha3ToAlpha2: [String: String] = [
        "USA": "US",
        "CAN": "CA",
        "GBR": "GB",
        "AUS": "AU",
        "DEU": "DE",
        "FRA": "FR",
        "ESP": "ES",
        "ITA": "IT",
        "MEX": "MX",
        "JPN": "JP",
        "CHN": "CN",
        "IND": "IN",
        "BRA": "BR",
    ]
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}

#if DEBUG
#Preview("Personal details") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            PersonalDetailsSheet(
                firstName: "Riley",
                middleName: "James",
                lastName: "Ready",
                dateOfBirth: "1992-04-15",
                countryOfCitizenship: "USA",
                taxIdLast4: "2901"
            )
        }
        .preferredColorScheme(.dark)
}

#Preview("Missing fields") {
    Color.sevinoSettingsBg
        .ignoresSafeArea()
        .overlay(alignment: .bottom) {
            PersonalDetailsSheet(
                firstName: "Riley",
                middleName: nil,
                lastName: "Ready",
                dateOfBirth: nil,
                countryOfCitizenship: nil,
                taxIdLast4: nil
            )
        }
        .preferredColorScheme(.dark)
}
#endif
