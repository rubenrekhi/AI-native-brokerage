import XCTest
@testable import Sevino

final class CashCardDataTests: XCTestCase {

    private func makeSample(
        reauthRelationshipId: UUID? = nil,
        enrollmentState: EnrollmentState = .active
    ) -> CashCardData {
        CashCardData(
            balance: 2412.08,
            apy: 0.032,
            thisMonthEarned: 6.43,
            daysAccrued: 22,
            lifetimeEarned: 41.87,
            lifetimeSince: Date(timeIntervalSince1970: 1_727_740_800),
            buyingPower: 2412.08,
            pendingDeposits: 100.50,
            interestPaidOut: .monthly,
            fdicInsuredLimit: 2_500_000,
            enrollmentState: enrollmentState,
            hasLinkedBank: true,
            reauthRelationshipId: reauthRelationshipId
        )
    }

    func test_reauthRelationshipId_roundTrips() throws {
        let id = UUID()
        let original = makeSample(reauthRelationshipId: id)

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(CashCardData.self, from: data)

        XCTAssertEqual(decoded.reauthRelationshipId, id)
    }

    func test_codableRoundTrip_preservesAllFields() throws {
        let original = makeSample()

        let data = try JSONEncoder().encode(original)
        let decoded = try JSONDecoder().decode(CashCardData.self, from: data)

        XCTAssertEqual(decoded, original)
    }

    func test_enrollmentState_roundTripsAllCases() throws {
        for state in [EnrollmentState.active, .pending, .notEnrolled, .unavailable] {
            let original = makeSample(enrollmentState: state)
            let data = try JSONEncoder().encode(original)
            let decoded = try JSONDecoder().decode(CashCardData.self, from: data)
            XCTAssertEqual(decoded.enrollmentState, state, "state: \(state)")
        }
    }

    func test_enrollmentState_encodesAsSnakeCaseRawValue() throws {
        let data = try JSONEncoder().encode(EnrollmentState.notEnrolled)
        XCTAssertEqual(String(data: data, encoding: .utf8), "\"not_enrolled\"")
    }

    func test_paidOutCadence_encodesAsLowercaseRawValue() throws {
        let data = try JSONEncoder().encode(PaidOutCadence.monthly)
        let raw = String(data: data, encoding: .utf8)

        XCTAssertEqual(raw, "\"monthly\"")
    }

    func test_paidOutCadence_roundTripsAllCases() throws {
        for cadence in PaidOutCadence.allCases {
            let encoded = try JSONEncoder().encode(cadence)
            let decoded = try JSONDecoder().decode(PaidOutCadence.self, from: encoded)
            XCTAssertEqual(decoded, cadence)
        }
    }

    func test_decode_fromJsonWithSnakeCaseKeysFails() {
        // Documents the expected key strategy: CashCardData uses camelCase keys.
        // Consumers encoding with .convertToSnakeCase must decode with .convertFromSnakeCase.
        let snakeJson = """
        {
            "balance": "2412.08",
            "apy": "0.032",
            "this_month_earned": "6.43",
            "days_accrued": 22,
            "lifetime_earned": "41.87",
            "lifetime_since": 0,
            "buying_power": "2412.08",
            "pending_deposits": "100.50",
            "interest_paid_out": "monthly",
            "fdic_insured_limit": "2500000",
            "has_linked_bank": true
        }
        """.data(using: .utf8)!

        XCTAssertThrowsError(try JSONDecoder().decode(CashCardData.self, from: snakeJson))
    }
}
