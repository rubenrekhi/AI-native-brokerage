import XCTest
@testable import Sevino

final class FundingServiceTests: XCTestCase {

    private var session: URLSession!

    override func setUp() {
        super.setUp()
        session = StubURLProtocol.makeSession()
    }

    override func tearDown() {
        StubURLProtocol.reset()
        session = nil
        super.tearDown()
    }

    // MARK: - createTransfer

    func test_createTransfer_postsToExpectedPathWithSerializedBody() async throws {
        let responseBody = Data(#"""
        {"id":"xfer_1","status":"QUEUED","amount":"500.00","direction":"INCOMING","created_at":null,"reason":null,"bank":null}
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/funding/transfers",
            response: .success(status: 200, body: responseBody)
        )

        let service = makeService()
        _ = try await service.createTransfer(
            relationshipId: "rel-123",
            amount: Decimal(string: "500")!,
            direction: .deposit
        )

        let sent = StubURLProtocol.lastRequest()
        XCTAssertEqual(sent?.httpMethod, "POST")

        let bodyData = try XCTUnwrap(sent?.httpBodyStream.flatMap { readAll($0) })
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: bodyData) as? [String: Any])
        XCTAssertEqual(json["relationship_id"] as? String, "rel-123")
        XCTAssertEqual(json["amount"] as? String, "500.00")
        XCTAssertEqual(json["direction"] as? String, "INCOMING")
    }

    func test_createTransfer_withdrawSendsOutgoing() async throws {
        let responseBody = Data(#"""
        {"id":"xfer_2","status":"QUEUED","amount":"25.50","direction":"OUTGOING","created_at":null,"reason":null,"bank":null}
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/funding/transfers",
            response: .success(status: 200, body: responseBody)
        )

        let service = makeService()
        _ = try await service.createTransfer(
            relationshipId: "rel-123",
            amount: Decimal(string: "25.5")!,
            direction: .withdraw
        )

        let bodyData = try XCTUnwrap(StubURLProtocol.lastRequest()?.httpBodyStream.flatMap { readAll($0) })
        let json = try XCTUnwrap(try JSONSerialization.jsonObject(with: bodyData) as? [String: Any])
        XCTAssertEqual(json["amount"] as? String, "25.50")
        XCTAssertEqual(json["direction"] as? String, "OUTGOING")
    }

    func test_createTransfer_decodesResponse() async throws {
        let responseBody = Data(#"""
        {
          "id":"xfer_1",
          "status":"QUEUED",
          "amount":"500.00",
          "direction":"INCOMING",
          "created_at":"2026-04-24T12:34:56.789Z",
          "reason":null,
          "bank":{"nickname":null,"account_mask":"4521","institution_name":"Chase"}
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/funding/transfers",
            response: .success(status: 200, body: responseBody)
        )

        let service = makeService()
        let response = try await service.createTransfer(
            relationshipId: "rel-1",
            amount: 500,
            direction: .deposit
        )

        XCTAssertEqual(response.id, "xfer_1")
        XCTAssertEqual(response.status, "QUEUED")
        XCTAssertEqual(response.amountValue, 500)
        XCTAssertEqual(response.direction, "INCOMING")
        XCTAssertEqual(response.bank?.institutionName, "Chase")
        XCTAssertEqual(response.bank?.accountMask, "4521")
        XCTAssertNotNil(response.createdAtDate)
    }

    // MARK: - listTransfers

    func test_listTransfers_unwrapsTransfersArray() async throws {
        let responseBody = Data(#"""
        {
          "transfers":[
            {"id":"x1","status":"COMPLETE","amount":"100.00","direction":"INCOMING","created_at":null,"reason":null,"bank":null},
            {"id":"x2","status":"QUEUED","amount":"50.00","direction":"OUTGOING","created_at":null,"reason":null,"bank":null}
          ]
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/funding/transfers",
            response: .success(status: 200, body: responseBody)
        )

        let service = makeService()
        let transfers = try await service.listTransfers()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
        XCTAssertEqual(transfers.count, 2)
        XCTAssertEqual(transfers.map(\.id), ["x1", "x2"])
    }

    func test_listTransfers_propagatesAPIError() async {
        let errorBody = Data(#"{"error":"Forbidden","code":"FORBIDDEN"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/funding/transfers",
            response: .success(status: 403, body: errorBody)
        )

        let service = makeService()
        do {
            _ = try await service.listTransfers()
            XCTFail("expected APIError")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "FORBIDDEN")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - getCashInterest

    func test_getCashInterest_getsExpectedPathAndDecodesResponse() async throws {
        let responseBody = Data(#"""
        {
          "balance": "2412.08",
          "apy": "0.0425",
          "this_month_earned": "6.43",
          "days_accrued": 22,
          "lifetime_earned": "41.87",
          "lifetime_since": "2025-10-01T00:00:00+00:00",
          "buying_power": "2412.08",
          "pending_deposits": "100.50",
          "interest_paid_out": "monthly",
          "fdic_insured_limit": "2500000",
          "sweep_status": "ACTIVE"
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/cash-interest",
            response: .success(status: 200, body: responseBody)
        )

        let service = makeService()
        let response = try await service.getCashInterest()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "GET")
        XCTAssertEqual(response.balance, "2412.08")
        XCTAssertEqual(response.apy, "0.0425")
        XCTAssertEqual(response.thisMonthEarned, "6.43")
        XCTAssertEqual(response.daysAccrued, 22)
        XCTAssertEqual(response.lifetimeEarned, "41.87")
        XCTAssertEqual(response.lifetimeSince, "2025-10-01T00:00:00+00:00")
        XCTAssertEqual(response.interestPaidOut, "monthly")
        XCTAssertEqual(response.sweepStatus, "ACTIVE")
        XCTAssertNotNil(response.lifetimeSinceDate)
    }

    func test_getCashInterest_propagatesAPIError() async {
        let errorBody = Data(#"{"error":"Alpaca down","code":"ALPACA_UNAVAILABLE"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/cash-interest",
            response: .success(status: 503, body: errorBody)
        )

        let service = makeService()
        do {
            _ = try await service.getCashInterest()
            XCTFail("expected APIError")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "ALPACA_UNAVAILABLE")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - enrollCashInterest

    func test_enrollCashInterest_postsToCorrectPathAndDecodes() async throws {
        let responseBody = Data(#"""
        {
          "balance": "2412.08",
          "apy": "0.0425",
          "this_month_earned": "6.43",
          "days_accrued": 22,
          "lifetime_earned": "41.87",
          "lifetime_since": "2025-10-01T00:00:00+00:00",
          "buying_power": "2412.08",
          "pending_deposits": "100.50",
          "interest_paid_out": "monthly",
          "fdic_insured_limit": "2500000",
          "sweep_status": "PENDING_CHANGE",
          "enrollment_state": "pending"
        }
        """#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/cash-interest/enroll",
            response: .success(status: 202, body: responseBody)
        )

        let service = makeService()
        let response = try await service.enrollCashInterest()

        XCTAssertEqual(StubURLProtocol.lastRequest()?.httpMethod, "POST")
        XCTAssertEqual(response.enrollmentState, .pending)
        XCTAssertEqual(response.apy, "0.0425")
        XCTAssertEqual(response.sweepStatus, "PENDING_CHANGE")
    }

    func test_enrollCashInterest_propagatesAPIError() async {
        let errorBody = Data(#"{"error":"Alpaca down","code":"ALPACA_UNAVAILABLE"}"#.utf8)
        StubURLProtocol.register(
            host: "api.example.com",
            path: "/v1/brokerage/cash-interest/enroll",
            response: .success(status: 503, body: errorBody)
        )

        let service = makeService()
        do {
            _ = try await service.enrollCashInterest()
            XCTFail("expected APIError")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "ALPACA_UNAVAILABLE")
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    // MARK: - TransferResponse helpers

    func test_amountValue_parsesDecimalString() {
        let response = TransferResponse(
            id: "x", status: "QUEUED", amount: "123.45",
            direction: "INCOMING", createdAt: nil, reason: nil, bank: nil
        )
        XCTAssertEqual(response.amountValue, Decimal(string: "123.45"))
    }

    func test_amountValue_returnsZeroForMalformedAmount() {
        let response = TransferResponse(
            id: "x", status: "QUEUED", amount: "oops",
            direction: "INCOMING", createdAt: nil, reason: nil, bank: nil
        )
        XCTAssertEqual(response.amountValue, 0)
    }

    func test_createdAtDate_parsesFractionalSeconds() {
        let response = TransferResponse(
            id: "x", status: "QUEUED", amount: "0",
            direction: "INCOMING",
            createdAt: "2026-04-24T12:34:56.789Z",
            reason: nil, bank: nil
        )
        XCTAssertNotNil(response.createdAtDate)
    }

    func test_createdAtDate_parsesNoFractionalSeconds() {
        let response = TransferResponse(
            id: "x", status: "QUEUED", amount: "0",
            direction: "INCOMING",
            createdAt: "2026-04-24T12:34:56Z",
            reason: nil, bank: nil
        )
        XCTAssertNotNil(response.createdAtDate)
    }

    func test_createdAtDate_returnsNilForNil() {
        let response = TransferResponse(
            id: "x", status: "QUEUED", amount: "0",
            direction: "INCOMING", createdAt: nil, reason: nil, bank: nil
        )
        XCTAssertNil(response.createdAtDate)
    }

    // MARK: - Helpers

    private func makeService() -> FundingService {
        let client = APIClient(
            baseURL: "https://api.example.com",
            session: session,
            tokenProvider: { nil }
        )
        return FundingService(api: client)
    }

    private func readAll(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: 1024)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }
}
