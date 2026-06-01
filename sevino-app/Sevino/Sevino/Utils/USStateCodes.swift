import Foundation

/// US state/territory codes Alpaca's KYC `contact.state` accepts: 50 states + DC
/// + the territories AS, GU, MP, PR, VI, UM. Mirrors `US_STATE_CODES` in
/// `sevino-api/app/schemas/_states.py` — keep the two in sync.
enum USStateCodes {
    static let all: Set<String> = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC",
        "AS", "GU", "MP", "PR", "VI", "UM",
    ]

    static func isValid(_ code: String) -> Bool {
        all.contains(code.trimmingCharacters(in: .whitespaces).uppercased())
    }
}
