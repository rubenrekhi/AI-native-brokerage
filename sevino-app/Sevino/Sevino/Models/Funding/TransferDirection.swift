import Foundation

/// Direction of an ACH transfer relative to the brokerage account.
enum TransferDirection: String, Codable, Equatable, Hashable, Identifiable {
    /// Bank → brokerage (Alpaca `INCOMING`).
    case deposit
    /// Brokerage → bank (Alpaca `OUTGOING`).
    case withdraw

    var id: String { rawValue }

    /// Wire value sent to the backend in `TransferRequest.direction`.
    var apiValue: String {
        switch self {
        case .deposit: "INCOMING"
        case .withdraw: "OUTGOING"
        }
    }
}
