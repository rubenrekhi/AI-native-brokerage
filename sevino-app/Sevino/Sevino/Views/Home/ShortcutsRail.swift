import SwiftUI

/// Owns the shortcuts view model. The expansion state lives on the parent
/// (`HomeView`) because expanding the rail also hides the greeting — the two
/// views share the same y-region of the screen, so the parent coordinates
/// who renders. When `isExpanded` is true, every shortcut renders inline
/// (no bottom sheet); when false, only the top 3 + a "Show more" pill.
struct ShortcutsRail: View {
    let scale: CGFloat
    @Binding var isExpanded: Bool
    let onSelect: (String) -> Void

    @State private var viewModel = ShortcutsViewModel()

    var body: some View {
        HomeChatSuggestions(
            scale: scale,
            shortcuts: isExpanded ? viewModel.shortcuts : viewModel.topShortcuts,
            canExpand: viewModel.hasOverflow,
            isExpanded: isExpanded,
            onSelect: onSelect,
            onToggleExpand: {
                withAnimation(.easeInOut(duration: 0.25)) {
                    isExpanded.toggle()
                }
            }
        )
        .task { await viewModel.load() }
        .onChange(of: viewModel.hasOverflow) { _, hasOverflow in
            // If a reload drops the overflow (e.g. fewer shortcuts came back),
            // collapse so the user doesn't end up stuck in an expanded state
            // with a stale "Show less" pill that has nothing extra to show.
            if !hasOverflow && isExpanded {
                isExpanded = false
            }
        }
    }
}
