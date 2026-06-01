import XCTest
@testable import Sevino

/**
 Round-trip tests for the HIL `ConfirmationBlock`.

 The reference JSON mirrors `app/ai/blocks.py:ConfirmationBlock` and what the
 backend streams from `transfer_operations` / the confirm endpoint. If the
 wire shape changes, this file changes in lockstep — there is no codegen.
 */
final class ConfirmationBlockTests: XCTestCase {

    private static let pendingJSON = """
    {
      "type": "confirmation",
      "block_id": "blk_cf",
      "action_id": "11111111-1111-1111-1111-111111111111",
      "kind": "transfer",
      "title": "Confirm deposit",
      "rows": [
        {"label": "Amount", "value": "$500.00"},
        {"label": "Transfer", "value": "Chase ••1234 → Sevino"}
      ],
      "details": {
        "operation": "deposit",
        "direction": "INCOMING",
        "amount": "500.00",
        "currency": "USD",
        "bank_institution": "Chase",
        "bank_mask": "1234",
        "bank_nickname": "Checking"
      },
      "confirm_label": "Confirm deposit",
      "cancel_label": "Cancel",
      "hold_to_confirm": true,
      "status": "pending"
    }
    """

    func testConfirmationBlockDecodesAndRoundTrips() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self, from: Data(Self.pendingJSON.utf8)
        )
        guard case .confirmation(let cb) = decoded else {
            return XCTFail("expected .confirmation variant, got \(decoded)")
        }
        XCTAssertEqual(cb.blockId, "blk_cf")
        XCTAssertEqual(cb.actionId, "11111111-1111-1111-1111-111111111111")
        XCTAssertEqual(cb.kind, "transfer")
        XCTAssertEqual(cb.title, "Confirm deposit")
        XCTAssertEqual(cb.rows.count, 2)
        XCTAssertEqual(cb.rows[0].label, "Amount")
        XCTAssertEqual(cb.rows[0].value, "$500.00")
        XCTAssertEqual(cb.details.operation, "deposit")
        XCTAssertEqual(cb.details.amount, "500.00")
        // snake_case → camelCase via convertFromSnakeCase
        XCTAssertEqual(cb.details.bankInstitution, "Chase")
        XCTAssertEqual(cb.details.bankMask, "1234")
        XCTAssertEqual(cb.details.bankNickname, "Checking")
        XCTAssertTrue(cb.holdToConfirm)
        XCTAssertEqual(cb.status, "pending")
        XCTAssertTrue(cb.isPending)

        let reEncoded = try JSONEncoder.sevino().encode(decoded)
        let reDecoded = try JSONDecoder.sevino().decode(
            Block.self, from: reEncoded
        )
        XCTAssertEqual(decoded, reDecoded)
    }

    func testExecutedConfirmationIsNotPending() throws {
        let json = Self.pendingJSON.replacingOccurrences(
            of: "\"status\": \"pending\"", with: "\"status\": \"executed\""
        )
        let decoded = try JSONDecoder.sevino().decode(
            Block.self, from: Data(json.utf8)
        )
        guard case .confirmation(let cb) = decoded else {
            return XCTFail("expected .confirmation variant")
        }
        XCTAssertEqual(cb.status, "executed")
        XCTAssertFalse(cb.isPending)
    }

    func testWithStatusReplacesOnlyStatus() throws {
        let decoded = try JSONDecoder.sevino().decode(
            Block.self, from: Data(Self.pendingJSON.utf8)
        )
        guard case .confirmation(let cb) = decoded else {
            return XCTFail("expected .confirmation variant")
        }
        let superseded = cb.withStatus("superseded")
        XCTAssertEqual(superseded.status, "superseded")
        XCTAssertFalse(superseded.isPending)
        XCTAssertEqual(superseded.actionId, cb.actionId)
        XCTAssertEqual(superseded.rows, cb.rows)
        XCTAssertEqual(superseded.details, cb.details)
    }
}
