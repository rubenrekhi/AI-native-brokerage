import SwiftUI

/// Attaches the temporary transfer-flow sheet to a view. Extracted from `HomeView`
/// to keep its body within the Swift type-checker's complexity budget.
struct TransferSheetPresenter: ViewModifier {
    @Bindable var transferViewModel: TransferViewModel
    let fundingViewModel: FundingViewModel
    let scale: CGFloat

    func body(content: Content) -> some View {
        content.sheet(
            item: Binding(
                get: { transferViewModel.direction },
                set: { if $0 == nil { transferViewModel.cancel() } }
            )
        ) { direction in
            TransferFlowSheet(
                transferViewModel: transferViewModel,
                fundingViewModel: fundingViewModel,
                direction: direction,
                scale: scale
            )
        }
    }
}
