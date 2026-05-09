import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.dependencies.portfolio import (
    AlpacaAccountContext,
    get_alpaca_account_context,
)
from app.exceptions import ConflictError


@pytest.fixture
def db_mock():
    return AsyncMock()


async def test_returns_context_on_happy_path(db_mock):
    user_uuid = uuid.uuid4()
    row = SimpleNamespace(
        alpaca_account_id="acc_abc",
        account_status="ACTIVE",
    )
    with patch(
        "app.dependencies.portfolio.BrokerageAccountRepository.get_by_user_id",
        new=AsyncMock(return_value=row),
    ) as get_mock:
        ctx = await get_alpaca_account_context(user_id=str(user_uuid), db=db_mock)

    assert ctx == AlpacaAccountContext(
        user_id=user_uuid,
        alpaca_account_id="acc_abc",
        account_status="ACTIVE",
    )
    get_mock.assert_awaited_once_with(db_mock, user_uuid)


async def test_missing_row_raises_conflict(db_mock):
    user_uuid = uuid.uuid4()
    with patch(
        "app.dependencies.portfolio.BrokerageAccountRepository.get_by_user_id",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(ConflictError) as exc_info:
            await get_alpaca_account_context(user_id=str(user_uuid), db=db_mock)

    assert exc_info.value.code == "ACCOUNT_NOT_ACTIVE"
    assert exc_info.value.detail == {"account_status": None}


@pytest.mark.parametrize(
    "status", ["SUBMITTED", "APPROVED", "REJECTED", "ACCOUNT_UPDATED", "KYC_REVIEW"]
)
async def test_non_active_status_raises_conflict(db_mock, status):
    user_uuid = uuid.uuid4()
    row = SimpleNamespace(alpaca_account_id="acc_abc", account_status=status)
    with patch(
        "app.dependencies.portfolio.BrokerageAccountRepository.get_by_user_id",
        new=AsyncMock(return_value=row),
    ):
        with pytest.raises(ConflictError) as exc_info:
            await get_alpaca_account_context(user_id=str(user_uuid), db=db_mock)

    assert exc_info.value.code == "ACCOUNT_NOT_ACTIVE"
    assert exc_info.value.detail == {"account_status": status}
