import Foundation
import Observation

@Observable
final class CashEnrollmentStatusViewModel {
    private(set) var state: EnrollmentState = .unavailable
    private(set) var apy: Decimal = 0
    private(set) var sweepEnrolledAt: Date?
    private(set) var isLoading = false
    private(set) var isEnrolling = false
    var error: String?

    private let service: any FundingServiceProtocol

    init(service: any FundingServiceProtocol = FundingService.shared) {
        self.service = service
    }

    func load() async {
        guard !isLoading else { return }
        error = nil
        isLoading = true
        defer { isLoading = false }
        do {
            hydrate(from: try await service.getCashInterest())
        } catch {
            self.error = error.localizedDescription
        }
    }

    func reenroll() async {
        guard !isEnrolling, !isLoading, state == .notEnrolled else { return }
        error = nil
        isEnrolling = true
        defer { isEnrolling = false }

        let previousState = state
        state = .pending
        do {
            hydrate(from: try await service.enrollCashInterest())
        } catch {
            self.error = error.localizedDescription
            state = previousState
        }
    }

    private func hydrate(from response: CashInterestResponse) {
        state = response.enrollmentState ?? .unavailable
        apy = Decimal(string: response.apy) ?? 0
        sweepEnrolledAt = response.lifetimeSinceDate
    }
}
