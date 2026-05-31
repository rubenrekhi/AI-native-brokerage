import SwiftUI

/// Owns the shortcuts view model and overflow-sheet state so `HomeView` swaps a
/// single call site. The inline top-3 list renders via `HomeChatSuggestions`;
/// the overflow sheet body is wired in S6.
struct ShortcutsRail: View {
    let scale: CGFloat
    let onSelect: (String) -> Void

    @State private var viewModel = ShortcutsViewModel()
    @State private var showOverflow = false

    var body: some View {
        HomeChatSuggestions(
            scale: scale,
            shortcuts: viewModel.topShortcuts,
            hasOverflow: viewModel.hasOverflow,
            onSelect: onSelect,
            onShowMore: { showOverflow = true }
        )
        .task { await viewModel.load() }
        .sheet(isPresented: $showOverflow) {
            EmptyView()
        }
    }
}
