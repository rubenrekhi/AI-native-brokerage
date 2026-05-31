import Foundation
@testable import Sevino

final class MockDigestAPIClient: DigestAPIClientProtocol, @unchecked Sendable {
    var todayResponse: DigestTodayResponseDTO?
    var todayError: Error?
    var dismissError: Error?
    private(set) var getTodaysDigestCallCount = 0
    private(set) var dismissDigestCallCount = 0

    func getTodaysDigest() async throws -> DigestTodayResponseDTO? {
        getTodaysDigestCallCount += 1
        if let todayError { throw todayError }
        return todayResponse
    }

    func dismissDigest() async throws {
        dismissDigestCallCount += 1
        if let dismissError { throw dismissError }
    }
}
