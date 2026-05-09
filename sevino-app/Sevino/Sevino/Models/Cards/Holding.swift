import Foundation

/// One row in the live holdings modal — the synthetic CASH row at index 0
/// or one open position. Decimal-typed; the view formats at render time
/// using `NumberFormatting` helpers. Sign coloring and future sort order
/// derive directly from these fields (`unrealizedPl >= 0`, etc.).
struct Holding: Identifiable, Equatable {
    var id: String { ticker }
    let ticker: String
    let isCash: Bool
    let qty: Decimal?
    let marketValue: Decimal
    let unrealizedPl: Decimal?
    let unrealizedPlpc: Decimal?
    let changeToday: Decimal?
    let changeTodayPercent: Decimal?
    let avgEntryPrice: Decimal?
}
