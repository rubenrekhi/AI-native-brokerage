import time
from collections.abc import Callable

import httpx
import pytest

from app.services.alpaca_broker import AlpacaBrokerService


@pytest.fixture
def make_alpaca_service() -> Callable[[Callable[[httpx.Request], httpx.Response]], AlpacaBrokerService]:
    """Build an AlpacaBrokerService whose AsyncClient uses MockTransport with `handler`.

    Pre-seeds an access token so the OAuth2 path isn't exercised.
    """

    def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> AlpacaBrokerService:
        service = AlpacaBrokerService()
        service._access_token = "fake-access-token"
        service._token_expires_at = time.time() + 3600
        service._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        )
        return service

    return _factory
