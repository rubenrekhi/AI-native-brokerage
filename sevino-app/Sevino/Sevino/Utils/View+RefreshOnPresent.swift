import SwiftUI

extension View {
    /// Fires `refresh` whenever `isPresented` transitions from `false` to `true`.
    ///
    /// Use on data-backed morphing views (e.g. `HoldingsMorphingView`) whose
    /// view-model already renders last-known data — the refresh runs in the
    /// background and values swap in place, so the user never sees a loading
    /// state on re-open. Uses `onChange` rather than `.task(id:)` so it does
    /// not fire on initial mount; first load stays the responsibility of the
    /// screen-level `.task { ... }` that owns the view-model's lifetime.
    ///
    /// Attach to a view that is **already mounted** when `isPresented` flips —
    /// typically the always-mounted outer container, never an inner branch
    /// gated by `if isPresented`. A view that first appears with
    /// `isPresented` already `true` will never observe the transition.
    func refreshOnPresent(
        _ isPresented: Bool,
        _ refresh: @escaping () async -> Void
    ) -> some View {
        onChange(of: isPresented) { _, new in
            if new { Task { await refresh() } }
        }
    }
}

private struct RefreshOnPresentPreview: View {
    @State private var isPresented = false
    @State private var refreshCount = 0

    var body: some View {
        VStack(spacing: 24) {
            Text("Refreshes fired: \(refreshCount)")
                .font(.system(size: 18, weight: .semibold))

            Button(isPresented ? "Close" : "Open") {
                isPresented.toggle()
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(32)
        .refreshOnPresent(isPresented) {
            refreshCount += 1
        }
    }
}

#Preview {
    RefreshOnPresentPreview()
}
