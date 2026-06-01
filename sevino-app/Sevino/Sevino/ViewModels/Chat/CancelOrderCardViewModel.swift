import Foundation
import Observation

/// A terminal broker rejection — the order can no longer be cancelled (already
/// filled / terminal at the broker). Drives the card to a non-retryable
/// `.failed` state, distinct from a transient error which stays retryable.
struct OrderNotCancellableError: LocalizedError, Equatable {
    let message: String
    var errorDescription: String? { message }
}

/// Drives one `CancelOrderCard`. The card surfaces a pending order with a
/// hold-to-cancel gesture; this model owns the local cancellation state and
/// runs the injected action.
///
/// The cancel action is an injected closure rather than a direct
/// `TradingService` call: previews and tests pass a stub, and the chat host
/// wires it to the real service. `localStatus` overrides `block.status` for
/// display until the next decode — there is no SSE status patch for this card
/// yet. `isRetryable` is cleared on a terminal broker rejection so the failed
/// receipt hides the retry control; transient errors stay retryable.
@Observable
@MainActor
final class CancelOrderCardViewModel {
    let block: CancelOrderBlock
    private let onCancel: (String) async throws -> Void

    private(set) var localStatus: OrderCancellationStatus
    private(set) var isCancelling = false
    private(set) var isRetryable = true
    private(set) var error: String?

    init(
        block: CancelOrderBlock,
        onCancel: @escaping (String) async throws -> Void
    ) {
        self.block = block
        self.onCancel = onCancel
        self.localStatus = block.status
    }

    func cancel() async {
        guard !isCancelling, isRetryable, localStatus != .cancelled else { return }
        isCancelling = true
        error = nil
        defer { isCancelling = false }

        do {
            try await onCancel(block.orderId)
            localStatus = .cancelled
        } catch let notCancellable as OrderNotCancellableError {
            error = notCancellable.message
            localStatus = .failed
            isRetryable = false
        } catch let apiError as APIError where apiError.code == APIError.Code.conflict {
            error = apiError.error
            localStatus = .failed
            isRetryable = false
        } catch {
            self.error = error.localizedDescription
            localStatus = .failed
        }
    }
}
