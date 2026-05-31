import Foundation

/// A tappable chat suggestion from `GET /v1/shortcuts`. Hand-mirrors
/// `app/schemas/shortcuts.py:Shortcut`; the backend's `magnitude` sort key is
/// server-side only (excluded from the wire format) so it has no field here.
struct Shortcut: Identifiable, Decodable, Equatable, Sendable {
    let id: UUID
    let text: String
    let category: ShortcutCategory
}

enum ShortcutCategory: String, Decodable, Sendable {
    case firstTime = "first_time"
    case portfolioState = "portfolio_state"
    case marketState = "market_state"
    case radarUpdate = "radar_update"
    case capability
    case quietState = "quiet_state"
}
