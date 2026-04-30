#if DEBUG
import Foundation
import Observation

/// Drives the dev-only trade-execution test surface: holds the form input,
/// builds the `TradeExecutionCard` payload, and performs the place / cancel /
/// poll network calls. Only used by `TradeTestSheet` in settings and is
/// `#if DEBUG` gated so it never ships. When chat-driven order placement
/// lands the production card will receive its `TradeExecutionCardData` from
/// the backend over the chat stream — only the place/cancel/poll state
/// machine here is intended to migrate.
@Observable
final class TradeExecutionViewModel {

    enum AmountType: String, CaseIterable, Identifiable {
        case notional
        case qty

        var id: String { rawValue }
        var label: String { self == .notional ? "Notional ($)" : "Quantity" }
    }

    enum OrderTypeChoice: String, CaseIterable, Identifiable {
        case market
        case limit

        var id: String { rawValue }
        var label: String { self == .market ? "Market" : "Limit" }
    }

    private let tradingService: any TradingServiceProtocol

    var symbol: String = "AAPL"
    var side: TradeSide = .buy
    var orderType: OrderTypeChoice = .market
    var amount: String = "100.00"
    var amountType: AmountType = .notional
    var limitPrice: String = ""

    private(set) var cardData: TradeExecutionCardData?
    /// Reflects the *placement* outcome only — `confirmTrade` is the sole
    /// writer. Cancel and poll surface their failures via `actionError` so a
    /// failed refresh doesn't lie about whether the order was placed.
    private(set) var tradeState: TradeExecutionState = .pending
    private(set) var lastOrderId: String?
    private(set) var lastOrderStatus: String?
    private(set) var isSubmitting: Bool = false
    /// Last cancel/poll error message; cleared on the next attempt.
    private(set) var actionError: String?

    init(tradingService: any TradingServiceProtocol = TradingService.shared) {
        self.tradingService = tradingService
    }

    /// Snapshot the current form input into a `TradeExecutionCardData` so the
    /// card can render. Resets any prior outcome so re-previewing after a
    /// success/error returns the user to the pending state.
    func prepareTrade() {
        cardData = makeCardData()
        tradeState = .pending
        lastOrderId = nil
        lastOrderStatus = nil
        actionError = nil
    }

    /// POST the order and transition the card state. Surfaces the backend's
    /// user-facing message on `APIError`; falls back to a generic string for
    /// transport failures.
    func confirmTrade() async {
        guard !isSubmitting else { return }
        isSubmitting = true
        defer { isSubmitting = false }

        let request = makePlaceOrderRequest()
        do {
            let response = try await tradingService.placeOrder(request)
            lastOrderId = response.id
            lastOrderStatus = response.status
            tradeState = .success
        } catch let apiError as APIError {
            tradeState = .error(apiError.error)
        } catch {
            tradeState = .error(error.localizedDescription)
        }
    }

    /// DELETE the most recently placed order. Surfaces failures (e.g.
    /// attempting to cancel a terminal order) via `actionError` so the
    /// placement card stays accurate.
    func cancelTrade() async {
        guard let lastOrderId, !isSubmitting else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        actionError = nil
        do {
            let response = try await tradingService.cancelOrder(id: lastOrderId)
            lastOrderStatus = response.status
        } catch let apiError as APIError {
            actionError = apiError.error
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// GET the latest order state — used by the test sheet to refresh the
    /// status pill after Alpaca processes the order asynchronously.
    func pollStatus() async {
        guard let lastOrderId, !isSubmitting else { return }
        isSubmitting = true
        defer { isSubmitting = false }
        actionError = nil
        do {
            let response = try await tradingService.getOrder(id: lastOrderId)
            lastOrderStatus = response.status
        } catch let apiError as APIError {
            actionError = apiError.error
        } catch {
            actionError = error.localizedDescription
        }
    }

    private func makeCardData() -> TradeExecutionCardData {
        let trimmedSymbol = symbol.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let amountDisplay: String
        switch amountType {
        case .notional:
            amountDisplay = formatCurrency(amount)
        case .qty:
            amountDisplay = "\(amount) sh"
        }
        let orderTypeDisplay = orderType == .market
            ? "Market Order"
            : "Limit Order @ \(formatCurrency(limitPrice))"

        return TradeExecutionCardData(
            side: side,
            ticker: trimmedSymbol,
            companyName: trimmedSymbol,
            exchange: "—",
            orderType: orderTypeDisplay,
            amount: amountDisplay,
            estimatedShares: "—",
            currentPrice: "—",
            estimatedTotal: amountType == .notional ? formatCurrency(amount) : "—",
            disclaimer: "Test order placed against the sandbox brokerage."
        )
    }

    private func makePlaceOrderRequest() -> PlaceOrderRequest {
        let trimmedSymbol = symbol.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let qty: String? = amountType == .qty ? amount : nil
        let notional: String? = amountType == .notional ? amount : nil
        let limit: String? = orderType == .limit
            ? limitPrice.trimmingCharacters(in: .whitespacesAndNewlines)
            : nil

        return PlaceOrderRequest(
            symbol: trimmedSymbol,
            side: side.rawValue,
            type: orderType.rawValue,
            qty: qty,
            notional: notional,
            limitPrice: limit,
            conversationId: nil
        )
    }

    private func formatCurrency(_ raw: String) -> String {
        Decimal(string: raw).map {
            $0.formatted(.currency(code: "USD").locale(Locale(identifier: "en_US")))
        } ?? raw
    }
}
#endif
