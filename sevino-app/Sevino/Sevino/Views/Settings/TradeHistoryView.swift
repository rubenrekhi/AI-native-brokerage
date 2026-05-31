import SwiftUI

struct TradeHistoryView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.textSizeMultiplier) private var textMultiplier

    @State private var vm: TradeHistoryViewModel
    @State private var baseScale: CGFloat = 1

    private var scale: CGFloat { baseScale * textMultiplier }

    init(vm: TradeHistoryViewModel = TradeHistoryViewModel()) {
        _vm = State(initialValue: vm)
    }

    var body: some View {
        SevinoGlassContainer {
            VStack(spacing: 0) {
                SettingsHeaderView(title: L10n.Settings.tradeHistory, scale: scale, onBack: { dismiss() })
                    .padding(.bottom, 16 * scale)

                filterBar
                    .padding(.bottom, 16 * scale)

                content
            }
            .padding(.horizontal, 20 * scale)
            .padding(.top, 12 * scale)
        }
        .background {
            Color.sevinoSettingsBg
                .ignoresSafeArea()
        }
        .onGeometryChange(for: CGFloat.self) { proxy in
            proxy.size.width
        } action: { width in
            baseScale = width / 393
        }
        .navigationBarBackButtonHidden()
        .task { await vm.load() }
        .alert(
            L10n.Settings.tradeHistoryErrorTitle,
            isPresented: Bindable(vm).isShowingError,
            presenting: vm.error
        ) { _ in
            Button(L10n.General.ok, role: .cancel, action: vm.clearError)
        } message: { message in
            Text(message)
        }
    }

    private var filterBar: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 8 * scale) {
                FilterMenu(
                    label: L10n.Settings.tradeHistoryFilterStatus,
                    selectionLabel: statusLabel(vm.statusFilter),
                    isActive: vm.statusFilter != .all,
                    scale: scale,
                ) {
                    Picker("", selection: Bindable(vm).statusFilter) {
                        Text(L10n.Settings.tradeHistoryFilterAll).tag(TradeStatusFilter.all)
                        Text(L10n.Settings.tradeHistoryFilterPending).tag(TradeStatusFilter.pending)
                        Text(L10n.Settings.tradeHistoryFilterCompleted).tag(TradeStatusFilter.completed)
                        Text(L10n.Settings.tradeHistoryFilterFailed).tag(TradeStatusFilter.failed)
                    }
                }

                FilterMenu(
                    label: L10n.Settings.tradeHistoryFilterSide,
                    selectionLabel: sideLabel(vm.sideFilter),
                    isActive: vm.sideFilter != .all,
                    scale: scale,
                ) {
                    Picker("", selection: Bindable(vm).sideFilter) {
                        Text(L10n.Settings.tradeHistoryFilterAll).tag(TradeSideFilter.all)
                        Text(L10n.Settings.tradeHistoryFilterBuy).tag(TradeSideFilter.buy)
                        Text(L10n.Settings.tradeHistoryFilterSell).tag(TradeSideFilter.sell)
                    }
                }

                FilterMenu(
                    label: L10n.Settings.tradeHistoryFilterTimeframe,
                    selectionLabel: timeframeLabel(vm.timeframeFilter),
                    isActive: vm.timeframeFilter != .all,
                    scale: scale,
                ) {
                    Picker("", selection: Bindable(vm).timeframeFilter) {
                        Text(L10n.Settings.tradeHistoryFilterAll).tag(TradeTimeframeFilter.all)
                        Text(L10n.Settings.tradeHistoryFilter7d).tag(TradeTimeframeFilter.last7Days)
                        Text(L10n.Settings.tradeHistoryFilter30d).tag(TradeTimeframeFilter.last30Days)
                        Text(L10n.Settings.tradeHistoryFilter90d).tag(TradeTimeframeFilter.last90Days)
                    }
                }

                FilterMenu(
                    label: L10n.Settings.tradeHistoryFilterHoldings,
                    selectionLabel: vm.holdingsFilter ?? L10n.Settings.tradeHistoryFilterAll,
                    isActive: vm.holdingsFilter != nil,
                    scale: scale,
                ) {
                    Picker("", selection: Bindable(vm).holdingsFilter) {
                        Text(L10n.Settings.tradeHistoryFilterAll).tag(String?.none)
                        ForEach(vm.holdingsSymbols, id: \.self) { symbol in
                            Text(symbol).tag(String?.some(symbol))
                        }
                    }
                }
                .disabled(vm.holdingsSymbols.isEmpty && vm.holdingsFilter == nil)
            }
        }
        .scrollIndicators(.hidden)
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.orders.isEmpty {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let error = vm.error, vm.orders.isEmpty {
            errorState(message: error)
        } else if vm.filteredOrders.isEmpty {
            emptyState
        } else {
            orderList
        }
    }

    private var orderList: some View {
        ScrollView {
            LazyVStack(spacing: 12 * scale) {
                ForEach(vm.filteredOrders) { order in
                    TradeHistoryRow(order: order, scale: scale)
                }
            }
            .padding(.bottom, 16 * scale)
        }
        .scrollIndicators(.hidden)
        .refreshable { await vm.load() }
    }

    private var emptyState: some View {
        let isFiltered = vm.statusFilter != .all
            || vm.sideFilter != .all
            || vm.timeframeFilter != .all
            || vm.holdingsFilter != nil

        return ContentUnavailableView {
            Label(
                isFiltered
                    ? L10n.Settings.tradeHistoryFilteredEmptyTitle
                    : L10n.Settings.tradeHistoryEmptyTitle,
                systemImage: "chart.line.uptrend.xyaxis"
            )
        } description: {
            Text(
                isFiltered
                    ? L10n.Settings.tradeHistoryFilteredEmptyMessage
                    : L10n.Settings.tradeHistoryEmptyMessage
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func errorState(message: String) -> some View {
        VStack(spacing: 12 * scale) {
            Text(message)
                .font(.system(size: 14 * scale))
                .foregroundStyle(Color.sevinoNegative)
                .multilineTextAlignment(.center)

            Button(L10n.General.tryAgain, action: retry)
                .font(.system(size: 14 * scale, weight: .medium))
                .foregroundStyle(Color.sevinoSecondary)
                .frame(minWidth: 44, minHeight: 44)
                .padding(.horizontal, 16 * scale)
                .contentShape(Rectangle())
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.vertical, 16 * scale)
    }

    private func retry() {
        Task { await vm.load() }
    }

    private func statusLabel(_ filter: TradeStatusFilter) -> String {
        switch filter {
        case .all: L10n.Settings.tradeHistoryFilterStatus
        case .pending: L10n.Settings.tradeHistoryFilterPending
        case .completed: L10n.Settings.tradeHistoryFilterCompleted
        case .failed: L10n.Settings.tradeHistoryFilterFailed
        }
    }

    private func sideLabel(_ filter: TradeSideFilter) -> String {
        switch filter {
        case .all: L10n.Settings.tradeHistoryFilterSide
        case .buy: L10n.Settings.tradeHistoryFilterBuy
        case .sell: L10n.Settings.tradeHistoryFilterSell
        }
    }

    private func timeframeLabel(_ filter: TradeTimeframeFilter) -> String {
        switch filter {
        case .all: L10n.Settings.tradeHistoryFilterTimeframe
        case .last7Days: L10n.Settings.tradeHistoryFilter7d
        case .last30Days: L10n.Settings.tradeHistoryFilter30d
        case .last90Days: L10n.Settings.tradeHistoryFilter90d
        }
    }
}

private struct TradeHistoryRow: View {
    let order: OrderResponse
    let scale: CGFloat

    private var sideLabel: String {
        switch order.sideKind {
        case .buy: L10n.Settings.tradeHistoryBuyLabel
        case .sell: L10n.Settings.tradeHistorySellLabel
        case .unknown: order.side.uppercased()
        }
    }

    private var sideGlyph: String {
        switch order.sideKind {
        case .buy: "arrow.down"
        case .sell: "arrow.up"
        case .unknown: "circle"
        }
    }

    private var sideColor: Color {
        switch order.sideKind {
        case .buy: Color.sevinoPositive
        case .sell: Color.sevinoSecondary
        case .unknown: Color.sevinoGreyContrast
        }
    }

    private var quantityText: String? {
        // Partially-filled orders show "X of Y filled". Otherwise the resolved
        // quantity (filled if completed, requested otherwise).
        if order.status.lowercased() == "partially_filled",
           let filled = order.filledQty, let total = order.qty {
            return L10n.Settings.tradeHistoryPartialFill(filled: filled, total: total)
        }
        let qty = order.statusKind == .completed ? (order.filledQty ?? order.qty) : order.qty
        guard let qty else { return nil }
        return L10n.Settings.tradeHistoryShares(qty)
    }

    private var amountText: String? {
        // Prefer total cost basis (filled qty × avg price) when available;
        // fall back to notional if Alpaca returned that instead.
        if let qty = order.filledQtyValue, let price = order.filledAvgPriceValue {
            let total = qty * price
            return total.formatted(.currency(code: "USD"))
        }
        if let notional = order.notionalValue {
            return notional.formatted(.currency(code: "USD"))
        }
        return nil
    }

    private var dateText: String {
        guard let date = order.representativeDate else { return "" }
        return date.formatted(.dateTime.month(.abbreviated).day().year())
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12 * scale) {
            Image(systemName: sideGlyph)
                .font(.system(size: 14 * scale, weight: .bold))
                .foregroundStyle(sideColor)
                .frame(width: 36 * scale, height: 36 * scale)
                .background(Color.sevinoGreyAccent.opacity(0.2), in: .circle)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4 * scale) {
                HStack(spacing: 6 * scale) {
                    Text("\(sideLabel) \(order.symbol)")
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)

                    TradeStatusBadge(kind: order.statusKind, scale: scale)
                }

                if let quantityText {
                    Text(quantityText)
                        .font(.system(size: 13 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 0)

            VStack(alignment: .trailing, spacing: 4 * scale) {
                if let amountText {
                    Text(amountText)
                        .font(.system(size: 15 * scale, weight: .semibold))
                        .foregroundStyle(Color.sevinoSecondary)
                }

                if !dateText.isEmpty {
                    Text(dateText)
                        .font(.system(size: 12 * scale))
                        .foregroundStyle(Color.sevinoGreyContrast)
                }
            }
        }
        .padding(14 * scale)
        .modifier(SevinoGlass.card)
    }
}

private struct TradeStatusBadge: View {
    let kind: TradeStatusKind
    let scale: CGFloat

    private var label: String {
        switch kind {
        case .completed: L10n.Settings.tradeHistoryStatusCompleted
        case .pending: L10n.Settings.tradeHistoryStatusPending
        case .failed: L10n.Settings.tradeHistoryStatusFailed
        case .unknown: L10n.Settings.tradeHistoryStatusUnknown
        }
    }

    private var color: Color {
        switch kind {
        case .completed: Color.sevinoPositive
        case .pending: Color.sevinoWarning
        case .failed: Color.sevinoNegative
        case .unknown: Color.sevinoGreyContrast
        }
    }

    var body: some View {
        Text(label)
            .font(.system(size: 10 * scale, weight: .semibold))
            .tracking(0.5)
            .foregroundStyle(color)
            .padding(.horizontal, 8 * scale)
            .padding(.vertical, 3 * scale)
            .background(color.opacity(0.15), in: .capsule)
    }
}

#if DEBUG
#Preview("Loaded") {
    NavigationStack {
        TradeHistoryView(vm: .previewLoaded())
    }
    .preferredColorScheme(.dark)
}

#Preview("Empty") {
    NavigationStack {
        TradeHistoryView(vm: TradeHistoryViewModel(tradingService: PreviewEmptyTradingService()))
    }
    .preferredColorScheme(.dark)
}

private extension TradeHistoryViewModel {
    static func previewLoaded() -> TradeHistoryViewModel {
        TradeHistoryViewModel(tradingService: PreviewLoadedTradingService())
    }
}

private final class PreviewEmptyTradingService: TradingServiceProtocol, @unchecked Sendable {
    func listOrders(
        status: String?, side: String?, symbols: String?,
        after: Date?, until: Date?, limit: Int
    ) async throws -> [OrderResponse] { [] }

    func listPositions() async throws -> [PositionResponse] { [] }

    func placeOrder(_ request: PlaceOrderRequest) async throws -> PlaceOrderResponse {
        throw URLError(.unsupportedURL)
    }

    func cancelOrder(id: String) async throws -> OrderDetailResponse {
        throw URLError(.unsupportedURL)
    }

    func getOrder(id: String) async throws -> OrderDetailResponse {
        throw URLError(.unsupportedURL)
    }
}

private final class PreviewLoadedTradingService: TradingServiceProtocol, @unchecked Sendable {
    func listOrders(
        status: String?, side: String?, symbols: String?,
        after: Date?, until: Date?, limit: Int
    ) async throws -> [OrderResponse] {
        [
            .preview(id: "ord_1", symbol: "AAPL", side: "buy",
                qty: "10", filledQty: "10", filledAvgPrice: "184.20",
                status: "filled", filledAt: "2026-04-22T15:30:00Z"),
            .preview(id: "ord_2", symbol: "TSLA", side: "sell",
                qty: "5", filledQty: "2", filledAvgPrice: "240.10",
                status: "partially_filled", submittedAt: "2026-04-21T18:00:00Z"),
            .preview(id: "ord_3", symbol: "NVDA", side: "buy",
                qty: "3", filledQty: nil, filledAvgPrice: nil,
                status: "rejected", failedAt: "2026-04-19T10:05:00Z"),
        ]
    }

    func listPositions() async throws -> [PositionResponse] {
        [
            PositionResponse(symbol: "AAPL", assetClass: "us_equity", qty: "10", marketValue: "1842.00"),
            PositionResponse(symbol: "TSLA", assetClass: "us_equity", qty: "2", marketValue: "480.20"),
        ]
    }

    func placeOrder(_ request: PlaceOrderRequest) async throws -> PlaceOrderResponse {
        throw URLError(.unsupportedURL)
    }

    func cancelOrder(id: String) async throws -> OrderDetailResponse {
        throw URLError(.unsupportedURL)
    }

    func getOrder(id: String) async throws -> OrderDetailResponse {
        throw URLError(.unsupportedURL)
    }
}

private extension OrderResponse {
    static func preview(
        id: String,
        symbol: String,
        side: String,
        qty: String?,
        filledQty: String?,
        filledAvgPrice: String?,
        status: String,
        submittedAt: String? = nil,
        filledAt: String? = nil,
        failedAt: String? = nil
    ) -> OrderResponse {
        OrderResponse(
            id: id,
            clientOrderId: nil,
            symbol: symbol,
            assetClass: "us_equity",
            side: side,
            orderType: "market",
            timeInForce: "day",
            qty: qty,
            notional: nil,
            filledQty: filledQty,
            filledAvgPrice: filledAvgPrice,
            limitPrice: nil,
            stopPrice: nil,
            status: status,
            submittedAt: submittedAt,
            filledAt: filledAt,
            canceledAt: nil,
            expiredAt: nil,
            failedAt: failedAt,
            createdAt: submittedAt
        )
    }
}
#endif
