import Foundation

/// Formats backend-stored phone strings for display. Inputs come from
/// `auth.users.phone` / `auth.users.phone_change` (via `OnboardingStatusResponse`)
/// in normalized form — `+15551234567` or `15551234567` once GoTrue strips
/// the `+`. Output matches the entry-time format from `PhoneNumberViewModel`
/// so the resume screen reads continuously with the typing flow.
///
/// Anything that doesn't reduce to 10 digits, or 11 digits with a leading
/// `1`, passes through unchanged so we don't mangle a number we just don't
/// know how to format yet (international shapes are out of scope until the
/// app supports non-US sign-ups).
enum PhoneFormatter {
    static func format(_ raw: String) -> String {
        let digits = raw.filter(\.isNumber)
        let local: Substring
        switch digits.count {
        case 10:
            local = Substring(digits)
        case 11 where digits.first == "1":
            local = digits.dropFirst()
        default:
            return raw
        }
        let area = local.prefix(3)
        let mid = local.dropFirst(3).prefix(3)
        let end = local.dropFirst(6)
        return "(\(area)) \(mid)-\(end)"
    }
}
