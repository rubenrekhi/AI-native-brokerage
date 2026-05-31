import XCTest
@testable import Sevino

final class DigestCardDecodingTests: XCTestCase {
    func testAllDigestCardKindsDecode() throws {
        let cards = try JSONDecoder.sevino().decode([DigestCard].self, from: Self.allCardsJSON)

        XCTAssertEqual(cards.map(\.kind), [
            "dividends",
            "pending_order_activity",
            "big_move",
            "watchlist_move",
            "market_context",
            "radar_refresh",
            "earnings_result",
            "upcoming_earnings",
            "news",
        ])
        XCTAssertEqual(cards.first?.relatedSymbols, ["AAPL"])

        guard case .dividends(let dividends) = cards[0] else {
            return XCTFail("expected dividends card")
        }
        XCTAssertEqual(dividends.totalAmount, Decimal(string: "12.34"))
        XCTAssertEqual(dividends.payments.first?.amount, Decimal(string: "12.34"))

        guard case .pendingOrderActivity(let activity) = cards[1] else {
            return XCTFail("expected pending order activity card")
        }
        XCTAssertEqual(activity.filled.first?.qty, Decimal(string: "1.5"))
        XCTAssertEqual(activity.recurringExecuted.first?.notional, Decimal(string: "25.00"))

        guard case .earningsResult(let earnings) = cards[6] else {
            return XCTFail("expected earnings result card")
        }
        XCTAssertEqual(earnings.stockReactionPct, Decimal(string: "0.052"))
    }

    func testUnknownDigestCardKindThrows() {
        let payload = Data(#"[{"id":"00000000-0000-0000-0000-000000000001","kind":"unknown","priority":0,"related_symbols":[],"card_context":{}}]"#.utf8)

        XCTAssertThrowsError(try JSONDecoder.sevino().decode([DigestCard].self, from: payload))
    }

    private static let allCardsJSON = Data("""
    [
      {
        "id": "00000000-0000-0000-0000-000000000001",
        "kind": "dividends",
        "priority": 1,
        "related_symbols": ["AAPL"],
        "card_context": {"source": "test"},
        "payments": [{"symbol": "AAPL", "amount": "12.34", "paid_at": "2026-05-31T13:00:00Z"}],
        "total_amount": "12.34",
        "period_label": "May"
      },
      {
        "id": "00000000-0000-0000-0000-000000000002",
        "kind": "pending_order_activity",
        "priority": 2,
        "related_symbols": ["MSFT"],
        "card_context": {},
        "filled": [{"symbol": "MSFT", "name": "Microsoft", "side": "buy", "qty": "1.5", "notional": null}],
        "recurring_executed": [{"symbol": "VOO", "name": null, "side": "buy", "qty": null, "notional": "25.00"}],
        "recurring_skipped": []
      },
      {
        "id": "00000000-0000-0000-0000-000000000003",
        "kind": "big_move",
        "priority": 3,
        "related_symbols": ["NVDA"],
        "card_context": {},
        "symbol": "NVDA",
        "name": "NVIDIA",
        "prev_close": "100.00",
        "current": "108.00",
        "change_abs": "8.00",
        "change_pct": "0.08",
        "reason": null
      },
      {
        "id": "00000000-0000-0000-0000-000000000004",
        "kind": "watchlist_move",
        "priority": 4,
        "related_symbols": ["TSLA"],
        "card_context": {},
        "symbol": "TSLA",
        "name": "Tesla",
        "prev_close": "200.00",
        "current": "190.00",
        "change_abs": "-10.00",
        "change_pct": "-0.05",
        "reason": "Watchlist move"
      },
      {
        "id": "00000000-0000-0000-0000-000000000005",
        "kind": "market_context",
        "priority": 5,
        "related_symbols": [],
        "card_context": {},
        "direction": "mixed",
        "sp500_change_pct": "0.004",
        "nasdaq_change_pct": "-0.002",
        "summary": "Mixed session"
      },
      {
        "id": "00000000-0000-0000-0000-000000000006",
        "kind": "radar_refresh",
        "priority": 6,
        "related_symbols": [],
        "card_context": {},
        "refreshed_at": "2026-05-31T13:00:00Z",
        "new_count": 3,
        "removed_count": 1
      },
      {
        "id": "00000000-0000-0000-0000-000000000007",
        "kind": "earnings_result",
        "priority": 7,
        "related_symbols": ["AMZN"],
        "card_context": {},
        "symbol": "AMZN",
        "name": "Amazon",
        "grade": "A",
        "eps_actual": "1.23",
        "eps_estimate": "1.10",
        "rev_actual": "1000000000.00",
        "rev_estimate": null,
        "stock_reaction_pct": "0.052",
        "beat_miss_highlights": ["EPS beat"]
      },
      {
        "id": "00000000-0000-0000-0000-000000000008",
        "kind": "upcoming_earnings",
        "priority": 8,
        "related_symbols": ["META"],
        "card_context": {},
        "symbol": "META",
        "name": "Meta",
        "reports_at": "2026-06-01T20:00:00Z",
        "relative_label": "tomorrow"
      },
      {
        "id": "00000000-0000-0000-0000-000000000009",
        "kind": "news",
        "priority": 9,
        "related_symbols": ["GOOG"],
        "card_context": {},
        "symbol": null,
        "headline": "Market news",
        "source": "Wire",
        "url": "https://example.com/news",
        "published_at": "2026-05-31T12:00:00Z",
        "summary": "Summary"
      }
    ]
    """.utf8)
}
