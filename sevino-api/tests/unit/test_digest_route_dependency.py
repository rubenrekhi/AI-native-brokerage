from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.routes.digest import _digest_service


@pytest.mark.asyncio
async def test_digest_service_dependency_passes_fmp_from_app_state():
    alpaca = object()
    market_data = object()
    fmp = object()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/digest/today",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    alpaca=alpaca,
                    market_data=market_data,
                    fmp=fmp,
                )
            ),
        }
    )

    dependency = _digest_service(request, db=object())
    service = await anext(dependency)
    try:
        assert service._alpaca is alpaca
        assert service._market_data is market_data
        assert service._fmp is fmp
    finally:
        await dependency.aclose()
