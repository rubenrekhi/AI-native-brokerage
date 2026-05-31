import Foundation

/// What the New tab should render: the picks list, or one of two empty states.
/// `firstBatch` covers the just-onboarded window before any batch lands;
/// `reviewed` covers a user who has starred every pick this week.
enum RadarNewTabState: Equatable {
    case populated
    case firstBatch
    case reviewed(weekday: String)
}

/// Projection of `RadarViewModel` for `RadarCard`. The split lists and the
/// pre-formatted next-batch weekday are computed on the view model; this struct
/// just carries them so the card stays free of the view model and stays
/// previewable.
struct RadarCardData: Equatable {
    let newItems: [RadarItem]
    let starredItems: [RadarItem]
    /// Localized weekday ("Monday") of the next batch, or nil when there is no
    /// future anchor — the New-tab empty state uses nil to pick first-batch copy.
    let nextRefreshWeekday: String?

    var newTabState: RadarNewTabState {
        if !newItems.isEmpty { return .populated }
        if let nextRefreshWeekday { return .reviewed(weekday: nextRefreshWeekday) }
        return .firstBatch
    }
}
