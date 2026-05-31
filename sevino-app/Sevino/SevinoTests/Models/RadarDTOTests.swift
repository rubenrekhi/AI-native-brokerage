import XCTest
@testable import Sevino

final class RadarDTOTests: XCTestCase {

    private let decoder = JSONDecoder.sevino()

    private var listJSON: Data {
        """
        {
            "items": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "symbol": "NVDA",
                    "company_name": "NVIDIA Corporation",
                    "context_blurb": "Major chipmaker in a sector you don't currently own",
                    "source": "ai_generated",
                    "bucket": "diversification",
                    "is_favorited": false,
                    "relevance_score": 0.87,
                    "expires_at": "2026-06-06T13:00:00Z",
                    "created_at": "2026-05-30T13:00:00.123456Z",
                    "price": "892.41",
                    "change_abs": "23.10",
                    "change_pct": "0.0267"
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "symbol": "AAPL",
                    "company_name": null,
                    "context_blurb": null,
                    "source": "user_added",
                    "bucket": null,
                    "is_favorited": true,
                    "relevance_score": null,
                    "expires_at": null,
                    "created_at": "2026-05-29T09:00:00Z",
                    "price": null,
                    "change_abs": null,
                    "change_pct": null
                }
            ],
            "next_refresh_at": "2026-06-06T13:00:00Z"
        }
        """.data(using: .utf8)!
    }

    func testDecodesAIItemWithOverlayFields() throws {
        let response = try decoder.decode(RadarListResponseDTO.self, from: listJSON)

        XCTAssertEqual(response.items.count, 2)
        XCTAssertNotNil(response.nextRefreshAt)

        let nvda = response.items[0]
        XCTAssertEqual(nvda.id, UUID(uuidString: "11111111-1111-1111-1111-111111111111"))
        XCTAssertEqual(nvda.symbol, "NVDA")
        XCTAssertEqual(nvda.companyName, "NVIDIA Corporation")
        XCTAssertEqual(nvda.source, .aiGenerated)
        XCTAssertEqual(nvda.bucket, "diversification")
        XCTAssertFalse(nvda.isFavorited)
        XCTAssertEqual(nvda.relevanceScore ?? 0, 0.87, accuracy: 0.0001)
        XCTAssertNotNil(nvda.expiresAt)
        XCTAssertEqual(nvda.price, Decimal(string: "892.41"))
        XCTAssertEqual(nvda.changePct, Decimal(string: "0.0267"))
    }

    func testDecodesUserAddedItemWithNullOverlay() throws {
        let response = try decoder.decode(RadarListResponseDTO.self, from: listJSON)

        let aapl = response.items[1]
        XCTAssertEqual(aapl.source, .userAdded)
        XCTAssertNil(aapl.companyName)
        XCTAssertNil(aapl.contextBlurb)
        XCTAssertNil(aapl.bucket)
        XCTAssertTrue(aapl.isFavorited)
        XCTAssertNil(aapl.relevanceScore)
        XCTAssertNil(aapl.expiresAt)
        XCTAssertNil(aapl.price)
        XCTAssertNil(aapl.changePct)
    }

    func testNextRefreshAtNullDecodesAsNil() throws {
        let json = #"{"items": [], "next_refresh_at": null}"#.data(using: .utf8)!

        let response = try decoder.decode(RadarListResponseDTO.self, from: json)

        XCTAssertTrue(response.items.isEmpty)
        XCTAssertNil(response.nextRefreshAt)
    }

    func testMalformedPriceStringThrows() {
        let json = """
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "symbol": "NVDA",
            "source": "ai_generated",
            "is_favorited": false,
            "created_at": "2026-05-30T13:00:00Z",
            "price": "not-a-number"
        }
        """.data(using: .utf8)!

        XCTAssertThrowsError(try decoder.decode(RadarItemDTO.self, from: json))
    }

    // MARK: - DTO -> UI mapping

    func testMapsOverlayFieldsToDisplayStrings() throws {
        let response = try decoder.decode(RadarListResponseDTO.self, from: listJSON)
        let now = Date(timeIntervalSince1970: 1_748_000_000)  // before expires_at

        let nvda = RadarAPIClient.item(from: response.items[0], now: now)
        XCTAssertEqual(nvda.ticker, "NVDA")
        XCTAssertEqual(nvda.description, "Major chipmaker in a sector you don't currently own")
        XCTAssertTrue(nvda.isPositive)
        XCTAssertFalse(nvda.price.isEmpty)
        XCTAssertFalse(nvda.changePercent.isEmpty)
        XCTAssertEqual(nvda.isStarred, false)

        let aapl = RadarAPIClient.item(from: response.items[1], now: now)
        XCTAssertEqual(aapl.description, "")
        XCTAssertTrue(aapl.price.isEmpty, "user_added rows carry no overlay off the wire")
        XCTAssertTrue(aapl.changePercent.isEmpty)
        XCTAssertTrue(aapl.expiresIn.isEmpty, "no expiry on user_added rows")
        XCTAssertTrue(aapl.isPositive, "nil change defaults to non-negative")
    }

    // MARK: - expiresIn formatting

    func testExpiresInNilWhenNoExpiry() {
        XCTAssertEqual(RadarAPIClient.expiresIn(until: nil, from: Date()), "")
    }

    func testExpiresInEmptyWhenAlreadyLapsed() {
        let now = Date(timeIntervalSince1970: 1_000_000)
        let past = Date(timeIntervalSince1970: 999_000)
        XCTAssertEqual(RadarAPIClient.expiresIn(until: past, from: now), "")
    }

    func testExpiresInDays() {
        let now = Date(timeIntervalSince1970: 0)
        let inSixDays = Date(timeIntervalSince1970: 6 * 86_400 + 100)
        XCTAssertEqual(RadarAPIClient.expiresIn(until: inSixDays, from: now), "6 days")
    }

    func testExpiresInSingularDay() {
        let now = Date(timeIntervalSince1970: 0)
        let inOneDay = Date(timeIntervalSince1970: 86_400 + 100)
        XCTAssertEqual(RadarAPIClient.expiresIn(until: inOneDay, from: now), "1 day")
    }

    func testExpiresInHours() {
        let now = Date(timeIntervalSince1970: 0)
        let inThreeHours = Date(timeIntervalSince1970: 3 * 3_600 + 60)
        XCTAssertEqual(RadarAPIClient.expiresIn(until: inThreeHours, from: now), "3 hours")
    }
}
