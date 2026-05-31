enum RadarTab: CaseIterable, Identifiable {
    case new
    case starred

    var id: Self { self }
}
