from unittest.mock import AsyncMock

from httpx import AsyncClient


async def test_health_all_ok(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_health_db_down(client: AsyncClient, mock_db: AsyncMock):
    mock_db.execute.side_effect = ConnectionError("db unreachable")

    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error", "redis": "ok"}


async def test_health_redis_down(client: AsyncClient, mock_arq: AsyncMock):
    mock_arq.ping.side_effect = ConnectionError("redis unreachable")

    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "ok", "redis": "error"}


async def test_health_all_down(
    client: AsyncClient, mock_db: AsyncMock, mock_arq: AsyncMock
):
    mock_db.execute.side_effect = ConnectionError("db unreachable")
    mock_arq.ping.side_effect = ConnectionError("redis unreachable")

    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error", "redis": "error"}
