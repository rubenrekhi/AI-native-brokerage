"""Smoke test for B0.6 brokerage_account fixtures."""

import pytest

from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


async def test_brokerage_account_fixture_active(test_brokerage_account):
    assert test_brokerage_account["account_status"] == "ACTIVE"
    assert test_brokerage_account["alpaca_account_id"].startswith("alpaca_")


async def test_brokerage_account_fixture_pending(test_brokerage_account_pending):
    assert test_brokerage_account_pending["account_status"] == "APPROVAL_PENDING"
    assert test_brokerage_account_pending["alpaca_account_id"].startswith("alpaca_")
