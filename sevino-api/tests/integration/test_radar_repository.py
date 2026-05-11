"""Integration tests for the radar_items table.

T1 scope: verifies the (user_id, symbol) unique constraint added in
migration ``f05ad387f3bf`` prevents a user from adding the same ticker
to their radar twice.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.radar_item import RadarItem
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


async def test_unique_constraint_blocks_duplicate_user_symbol(
    db_session, test_user
):
    db_session.add(RadarItem(user_id=test_user, symbol="AAPL"))
    await db_session.flush()

    db_session.add(RadarItem(user_id=test_user, symbol="AAPL"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
