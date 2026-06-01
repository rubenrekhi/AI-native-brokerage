from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import app.services.alpaca_broker as alpaca_broker
from app.exceptions import NotFoundError
from app.services.alpaca_broker import AlpacaBrokerError

ACCOUNT_ID = "382dd20d-1b4c-4b3a-95bb-0e8e0d5e7777"


class TestGetAprTiers:
    async def test_returns_deserialized_dict(self, make_alpaca_service):
        captured: dict = {}
        body = {
            "apr_tiers": [
                {
                    "id": "382dd20d-aaaa",
                    "currency": "USD",
                    "name": "standard",
                    "is_default": True,
                    "account_rate_bps": 425,
                    "correspondent_rate_bps": 25,
                }
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json=body)

        service = make_alpaca_service(handler)
        result = await service.get_apr_tiers()

        assert captured["method"] == "GET"
        assert captured["url"].endswith("/v1/cash_interest/apr_tiers")
        assert result == body
        assert result["apr_tiers"][0]["account_rate_bps"] == 425

    async def test_401_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "unauthorized"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_apr_tiers()

        assert info.value.status_code == 401

    async def test_404_raises_alpaca_broker_error_not_not_found(
        self, make_alpaca_service
    ):
        # APR tiers is not account-scoped, so a 404 must NOT be mapped to
        # NotFoundError(resource="alpaca_account") — it's a config error.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_apr_tiers()

        assert info.value.status_code == 404

    async def test_500_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "server error"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_apr_tiers()

        assert info.value.status_code == 500


class TestGetEodCashInterest:
    async def test_passes_account_id_only(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"interest": [], "next_page_token": None})

        service = make_alpaca_service(handler)
        await service.get_eod_cash_interest(account_id=ACCOUNT_ID)

        assert "/v1/reporting/eod/cash_interest" in captured["url"]
        assert captured["query"] == {"account_id": [ACCOUNT_ID]}

    async def test_raises_when_date_combined_with_after_or_before(
        self, make_alpaca_service
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"interest": [], "next_page_token": None})

        service = make_alpaca_service(handler)
        with pytest.raises(ValueError):
            await service.get_eod_cash_interest(
                account_id=ACCOUNT_ID,
                date="2024-06-11",
                after="2024-06-01",
            )
        with pytest.raises(ValueError):
            await service.get_eod_cash_interest(
                account_id=ACCOUNT_ID,
                date="2024-06-11",
                before="2024-06-30",
            )

    async def test_after_and_before_passed_when_no_date(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json={"interest": [], "next_page_token": None})

        service = make_alpaca_service(handler)
        await service.get_eod_cash_interest(
            account_id=ACCOUNT_ID, after="2024-06-01", before="2024-06-30"
        )

        assert captured["query"] == {
            "account_id": [ACCOUNT_ID],
            "after": ["2024-06-01"],
            "before": ["2024-06-30"],
        }

    async def test_unwraps_interest_array_from_response(self, make_alpaca_service):
        # Alpaca wraps daily records in {"interest": [...], "next_page_token": ...};
        # callers expect a flat list, so the service must unwrap.
        records = [
            {
                "date": "2024-06-11",
                "account_id": ACCOUNT_ID,
                "apr_tier_name": "standard",
                "currency": "USD",
                "cash_balance": "10000.00",
                "account_rate_bps": 425,
                "account_accrued_interest": "1.1806",
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"interest": records, "next_page_token": None}
            )

        service = make_alpaca_service(handler)
        result = await service.get_eod_cash_interest(account_id=ACCOUNT_ID)

        assert isinstance(result, list)
        assert result == records

    async def test_returns_empty_list_when_no_interest_key(self, make_alpaca_service):
        # Defensive: if Alpaca ever returns an empty body, callers still get a list.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        service = make_alpaca_service(handler)
        result = await service.get_eod_cash_interest(account_id=ACCOUNT_ID)

        assert result == []

    async def test_401_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "unauthorized"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_eod_cash_interest(account_id=ACCOUNT_ID)

        assert info.value.status_code == 401

    async def test_404_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "account not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.get_eod_cash_interest(account_id=ACCOUNT_ID)

    async def test_500_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "server error"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_eod_cash_interest(account_id=ACCOUNT_ID)

        assert info.value.status_code == 500


class TestGetInterestActivities:
    async def test_forwards_account_id_param(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        service = make_alpaca_service(handler)
        await service.get_interest_activities(account_id=ACCOUNT_ID)

        assert captured["method"] == "GET"
        assert "/v1/accounts/activities/INT" in captured["url"]
        assert captured["query"] == {"account_id": [ACCOUNT_ID]}

    async def test_returns_activities(self, make_alpaca_service):
        activities = [
            {
                "id": "20220208125959696::abc",
                "account_id": ACCOUNT_ID,
                "activity_type": "INT",
                "activity_sub_type": "SWP",
                "date": "2024-06-28",
                "net_amount": "34.42",
                "description": "June 2024 Sweep",
                "status": "executed",
                "symbol": "SWEEPFDIC",
                "qty": "34.42",
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=activities)

        service = make_alpaca_service(handler)
        result = await service.get_interest_activities(account_id=ACCOUNT_ID)

        assert result == activities

    async def test_forwards_after_until_when_provided(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        service = make_alpaca_service(handler)
        await service.get_interest_activities(
            account_id=ACCOUNT_ID,
            after="2026-05-01T00:00:00+00:00",
            until="2026-05-31T23:59:59+00:00",
        )

        assert captured["query"] == {
            "account_id": [ACCOUNT_ID],
            "after": ["2026-05-01T00:00:00+00:00"],
            "until": ["2026-05-31T23:59:59+00:00"],
        }

    async def test_paginate_walks_pages_via_page_token(self, make_alpaca_service):
        # A full page must trigger a follow-up whose page_token is the last
        # activity's id; the short second page ends the walk.
        page_size = alpaca_broker._ACTIVITY_PAGE_SIZE
        requests: list[dict] = []
        full_page = [{"id": f"id_{n}", "net_amount": "1.00"} for n in range(page_size)]
        short_page = [{"id": "id_tail", "net_amount": "1.00"}]

        def handler(request: httpx.Request) -> httpx.Response:
            query = parse_qs(urlparse(str(request.url)).query)
            requests.append(query)
            if "page_token" not in query:
                return httpx.Response(200, json=full_page)
            return httpx.Response(200, json=short_page)

        service = make_alpaca_service(handler)
        result = await service.get_interest_activities(
            account_id=ACCOUNT_ID, after="2026-01-01", paginate=True
        )

        assert len(requests) == 2
        assert requests[0]["page_size"] == [str(page_size)]
        assert requests[0]["direction"] == ["desc"]
        assert requests[0]["after"] == ["2026-01-01"]
        assert "page_token" not in requests[0]
        # Cursor = last id of the first page; window params carried forward.
        assert requests[1]["page_token"] == [f"id_{page_size - 1}"]
        assert requests[1]["after"] == ["2026-01-01"]
        assert len(result) == page_size + 1

    async def test_paginate_single_short_page_makes_one_request(
        self, make_alpaca_service
    ):
        requests: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(parse_qs(urlparse(str(request.url)).query))
            return httpx.Response(200, json=[{"id": "only", "net_amount": "2.00"}])

        service = make_alpaca_service(handler)
        result = await service.get_interest_activities(
            account_id=ACCOUNT_ID, paginate=True
        )

        assert len(requests) == 1
        assert len(result) == 1

    async def test_paginate_stops_at_max_pages(self, make_alpaca_service):
        # Every page is full → the walk stops at the cap instead of looping
        # forever on an account with more activity than the bound allows.
        page_size = alpaca_broker._ACTIVITY_PAGE_SIZE
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                200,
                json=[
                    {"id": f"p{calls['n']}_{i}", "net_amount": "1.00"}
                    for i in range(page_size)
                ],
            )

        service = make_alpaca_service(handler)
        result = await service.get_interest_activities(
            account_id=ACCOUNT_ID, paginate=True
        )

        assert calls["n"] == alpaca_broker._ACTIVITY_MAX_PAGES
        assert len(result) == alpaca_broker._ACTIVITY_MAX_PAGES * page_size

    async def test_no_pagination_params_when_paginate_false(
        self, make_alpaca_service
    ):
        # Default path is a single request with no page_size/direction — the
        # contract `brokerage` / `cash_interest` callers still rely on.
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[{"id": "x", "net_amount": "1.00"}] * 100)

        service = make_alpaca_service(handler)
        await service.get_interest_activities(account_id=ACCOUNT_ID)

        assert captured["query"] == {"account_id": [ACCOUNT_ID]}

    async def test_401_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "unauthorized"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_interest_activities(account_id=ACCOUNT_ID)

        assert info.value.status_code == 401

    async def test_404_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "account not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.get_interest_activities(account_id=ACCOUNT_ID)

    async def test_500_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "server error"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.get_interest_activities(account_id=ACCOUNT_ID)

        assert info.value.status_code == 500
