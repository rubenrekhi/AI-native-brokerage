import Foundation
import Observation

/// Thrown by the injected cancel closure when the transfer can no longer be
/// cancelled (e.g. it already settled). Treated as terminal — the card moves to
/// `.failed`, as opposed to a transient failure which stays `.pending`.
enum TransferCancellationError: LocalizedError, Equatable {
    case notCancellable

    var errorDescription: String? {
        L10n.CancelTransfer.cancellationFailed
    }
}

/// Drives a `CancelTransferCard`. The cancel call is an injected closure
/// (`onCancel`) so the view model never depends on a service directly.
///
/// `localStatus` shadows `block.status` so a cancellation reflects immediately
/// without waiting on an SSE patch.
@Observable
final class CancelTransferCardViewModel {
    let block: CancelTransferBlock

    private(set) var localStatus: TransferStatus
    private(set) var isCancelling = false
    private(set) var error: String?

    private let onCancel: (String) async throws -> Void

    init(
        block: CancelTransferBlock,
        onCancel: @escaping (String) async throws -> Void
    ) {
        self.block = block
        self.localStatus = block.status
        self.onCancel = onCancel
    }

    func cancel() async {
        guard !isCancelling, localStatus != .cancelled else { return }
        isCancelling = true
        error = nil
        defer { isCancelling = false }

        do {
            try await onCancel(block.transferId)
            localStatus = .cancelled
        } catch let cancellationError as TransferCancellationError {
            localStatus = .failed
            error = cancellationError.errorDescription
        } catch {
            // Transient failure: stay pending so the user can hold to retry.
            localStatus = .pending
            self.error = error.localizedDescription
        }
    }
}
