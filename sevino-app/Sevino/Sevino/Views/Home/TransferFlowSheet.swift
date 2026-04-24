import SwiftUI

/// Temporary host for `TransferCard` / `TransferConfirmationCard` until the chat
/// backend ships and an MCP renderer takes over presentation.
///
/// Renders the form first; once `TransferViewModel.confirmation` is populated by a
/// successful submission, swaps to the read-only receipt.
struct TransferFlowSheet: View {
    @Bindable var transferViewModel: TransferViewModel
    let fundingViewModel: FundingViewModel
    let direction: TransferDirection
    let scale: CGFloat

    var body: some View {
        ZStack {
            Color.sevinoPrimary.ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16 * scale) {
                    if let confirmation = transferViewModel.confirmation {
                        TransferConfirmationCard(
                            data: confirmation,
                            scale: scale,
                            onDismiss: transferViewModel.cancel
                        )
                    } else {
                        let data = cardData()
                        TransferCard(
                            data: data,
                            scale: scale,
                            onConfirm: { id, amount in handleConfirm(data: data, id: id, amount: amount) },
                            onDismiss: transferViewModel.cancel,
                            onLinkBank: fundingViewModel.requestBankLink
                        )
                    }

                    if transferViewModel.isSubmitting {
                        ProgressView()
                            .tint(Color.sevinoSecondary)
                    }
                }
                .padding(20 * scale)
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private func cardData() -> TransferCardData {
        transferViewModel.cardData(
            for: direction,
            relationships: fundingViewModel.relationships,
            availableBalance: fundingViewModel.cashBuyingPower,
            brokerageLabel: L10n.General.appName
        )
    }

    private func handleConfirm(data: TransferCardData, id: String, amount: Decimal) {
        let bank = data.bankAccounts.first { $0.id == id }
        Task {
            await transferViewModel.submit(
                bankAccountID: id,
                amount: amount,
                sourceBank: bank
            )
        }
    }
}
