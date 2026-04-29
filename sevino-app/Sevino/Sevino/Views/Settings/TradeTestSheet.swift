#if DEBUG
import SwiftUI

// MARK: - debug-only test surface; intentionally hardcoded English (no L10n)
// This file is gated behind `#if DEBUG` and never ships to production builds,
// so the project-wide rule against raw user-facing strings is waived here.

/// Dev-only test surface that exercises the trade-execution API end-to-end:
/// place an order, watch the `TradeExecutionCard` transition through pending
/// → success/error, and (for working orders) cancel or refresh the status.
/// Surfaced from `SettingsView` so we can verify the live integration before
/// the chat-driven flow is wired up. Gated behind `#if DEBUG` — must never
/// ship to production builds.
struct TradeTestSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Bindable var viewModel: TradeExecutionViewModel

    var body: some View {
        NavigationStack {
            Form {
                InputSection(viewModel: viewModel)
                if viewModel.cardData != nil {
                    CardSection(viewModel: viewModel)
                }
                if viewModel.lastOrderId != nil {
                    OrderSection(viewModel: viewModel, refresh: refresh, cancel: cancel)
                }
            }
            .navigationTitle("Test Trade Execution")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func refresh() {
        Task { await viewModel.pollStatus() }
    }

    private func cancel() {
        Task { await viewModel.cancelTrade() }
    }
}

private struct InputSection: View {
    @Bindable var viewModel: TradeExecutionViewModel

    var body: some View {
        Section("Order") {
            TextField("Symbol", text: $viewModel.symbol)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()

            Picker("Side", selection: $viewModel.side) {
                Text("Buy").tag(TradeSide.buy)
                Text("Sell").tag(TradeSide.sell)
            }
            .pickerStyle(.segmented)

            Picker("Type", selection: $viewModel.orderType) {
                ForEach(TradeExecutionViewModel.OrderTypeChoice.allCases) { type in
                    Text(type.label).tag(type)
                }
            }
            .pickerStyle(.segmented)

            Picker("Amount Type", selection: $viewModel.amountType) {
                ForEach(TradeExecutionViewModel.AmountType.allCases) { type in
                    Text(type.label).tag(type)
                }
            }
            .pickerStyle(.segmented)

            TextField("Amount", text: $viewModel.amount)
                .keyboardType(.decimalPad)

            if viewModel.orderType == .limit {
                TextField("Limit Price", text: $viewModel.limitPrice)
                    .keyboardType(.decimalPad)
            }

            Button("Preview Order", action: viewModel.prepareTrade)
        }
    }
}

private struct CardSection: View {
    let viewModel: TradeExecutionViewModel

    var body: some View {
        Section("Preview") {
            if let cardData = viewModel.cardData {
                TradeExecutionCard(
                    data: cardData,
                    state: viewModel.tradeState,
                    onConfirm: { await viewModel.confirmTrade() }
                )
                .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                .listRowBackground(Color.clear)
            }
        }
    }
}

private struct OrderSection: View {
    let viewModel: TradeExecutionViewModel
    let refresh: () -> Void
    let cancel: () -> Void

    var body: some View {
        Section("Last Order") {
            if let id = viewModel.lastOrderId {
                LabeledContent("Order ID", value: id)
                    .font(.footnote.monospaced())
            }
            if let status = viewModel.lastOrderStatus {
                LabeledContent("Status", value: status)
            }
            if let actionError = viewModel.actionError {
                Text(actionError)
                    .font(.footnote)
                    .foregroundStyle(Color.sevinoNegative)
            }
            Button("Refresh Status", action: refresh)
                .disabled(viewModel.isSubmitting)
            Button("Cancel Order", role: .destructive, action: cancel)
                .disabled(viewModel.isSubmitting)
        }
    }
}

#Preview {
    TradeTestSheet(viewModel: TradeExecutionViewModel())
}
#endif
