"""Unit tests for SettingsService business logic.

Exercises the service in isolation by mocking the repository layer, Alpaca,
and Supabase admin client. Integration behavior (real DB, real request/response
cycle) is covered by ``tests/integration/test_settings.py`` and
``tests/integration/test_settings_routes.py``.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, call

import pytest

from app.exceptions import ConflictError, NotFoundError
from app.schemas.onboarding import ProfileData
from app.schemas.settings import (
    ProfileUpdateRequest,
    SettingsProfileResponse,
    UserSettingsPatchRequest,
    UserSettingsResponse,
)
from app.services.alpaca_broker import PENDING_TRANSFER_STATUSES, AlpacaBrokerError
from app.services.settings import SettingsService, _build_alpaca_profile_update_payload
from app.services.supabase_admin import (
    SupabaseAdminError,
    SupabaseAdminUnavailableError,
)


USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ALPACA_ACCOUNT_ID = "alpaca_acc_42"


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def alpaca() -> AsyncMock:
    svc = AsyncMock()
    svc.get_trading_account.return_value = {
        "id": ALPACA_ACCOUNT_ID,
        "equity": "100.00",
        "cash": "0.00",
        "buying_power": "100.00",
        "portfolio_value": "100.00",
    }
    svc.list_positions.return_value = []
    svc.list_transfers.return_value = []
    return svc


def _make_brokerage(status: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id=ALPACA_ACCOUNT_ID,
        account_status=status,
    )


def _make_profile(**overrides) -> SimpleNamespace:
    defaults = {
        "id": USER_ID,
        "email": "riley@example.com",
        "first_name": "Riley",
        "middle_name": None,
        "last_name": "Johnson",
        "preferred_name": None,
        "phone_number": "+15551234567",
        "street_address": ["1 Main St"],
        "city": "New York",
        "state": "NY",
        "postal_code": "10001",
        "country_of_citizenship": "USA",
        "country_of_birth": "USA",
        "country_of_tax_residence": "USA",
        "date_of_birth": None,
        "attribution_source": None,
        "disclosures": None,
        "agreements_signed": None,
        "risk_disclosure_acknowledged_at": None,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------


class TestGetSettings:
    async def test_returns_defaults_when_no_row(self, db, mocker):
        mocker.patch(
            "app.services.settings.UserSettingsRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )

        result = await SettingsService.get_settings(db, USER_ID)

        assert result.user_id == USER_ID
        # Round-trip through the response schema so enum coercion is exercised
        # — catches regressions like `theme="SYSTEM"` that would crash the route.
        response = UserSettingsResponse.model_validate(result)
        assert response.theme.value == "system"
        assert response.text_size.value == "standard"
        assert response.notifications_enabled is True
        assert response.ai_internet_access is True

    async def test_returns_persisted_row_when_present(self, db, mocker):
        stored = SimpleNamespace(
            user_id=USER_ID,
            theme="dark",
            text_size="large",
            notifications_enabled=False,
            ai_internet_access=False,
        )
        mocker.patch(
            "app.services.settings.UserSettingsRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=stored,
        )

        result = await SettingsService.get_settings(db, USER_ID)

        response = UserSettingsResponse.model_validate(result)
        assert response.theme.value == "dark"
        assert response.text_size.value == "large"
        assert response.notifications_enabled is False
        assert response.ai_internet_access is False


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    async def test_update_partial_fields_only_sends_provided(self, db, mocker):
        upsert = mocker.patch(
            "app.services.settings.UserSettingsRepository.upsert",
            new_callable=AsyncMock,
        )

        await SettingsService.update_settings(
            db, USER_ID, UserSettingsPatchRequest(theme="dark")
        )

        upsert.assert_awaited_once_with(db, USER_ID, theme="dark")

    async def test_update_creates_row_on_first_call(self, db, mocker):
        """upsert receives provided fields; repo handles create-vs-update."""
        upsert = mocker.patch(
            "app.services.settings.UserSettingsRepository.upsert",
            new_callable=AsyncMock,
        )

        await SettingsService.update_settings(
            db,
            USER_ID,
            UserSettingsPatchRequest(
                theme="dark",
                text_size="large",
                notifications_enabled=False,
                ai_internet_access=False,
            ),
        )

        upsert.assert_awaited_once_with(
            db,
            USER_ID,
            theme="dark",
            text_size="large",
            notifications_enabled=False,
            ai_internet_access=False,
        )


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


class TestGetProfile:
    async def test_assembles_all_data(self, db, mocker):
        profile = _make_profile()
        financial = SimpleNamespace(
            financial_worries=None,
            investment_goals=["grow_wealth"],
            annual_income="$50K – $99K",
            net_worth=None,
            liquid_net_worth=None,
            income_stability=None,
            time_horizon=None,
            risk_scenario_response=None,
            max_loss_tolerance=None,
            experience_level=None,
            employment_info=None,
            funding_sources=None,
        )
        brokerage = SimpleNamespace(
            account_number="SEV123456",
            account_status="ACTIVE",
            kyc_results={"status": "approved"},
        )
        linked = [
            SimpleNamespace(
                id=uuid.uuid4(),
                alpaca_relationship_id="rel_1",
                institution_name="Bank",
                account_mask="0001",
                account_type="CHECKING",
                nickname="Main",
                status="APPROVED",
            )
        ]

        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=profile,
        )
        mocker.patch(
            "app.services.settings.FinancialProfileRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=financial,
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        )
        mocker.patch(
            "app.services.settings.AchRelationshipRepository.list_active_for_user",
            new_callable=AsyncMock,
            return_value=linked,
        )

        result = await SettingsService.get_profile(db, USER_ID)

        assert result.profile.first_name == "Riley"
        assert result.financial_profile is not None
        assert result.financial_profile.annual_income == "$50K – $99K"
        assert result.brokerage is not None
        assert result.brokerage.account_number == "SEV123456"
        assert len(result.linked_accounts) == 1
        assert result.linked_accounts[0].alpaca_relationship_id == "rel_1"
        assert result.member_since == profile.created_at

    async def test_handles_missing_financial(self, db, mocker):
        profile = _make_profile()
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=profile,
        )
        mocker.patch(
            "app.services.settings.FinancialProfileRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )
        mocker.patch(
            "app.services.settings.AchRelationshipRepository.list_active_for_user",
            new_callable=AsyncMock,
            return_value=[],
        )

        result = await SettingsService.get_profile(db, USER_ID)

        assert result.financial_profile is None
        assert result.brokerage is None
        assert result.linked_accounts == []

    async def test_missing_profile_raises_not_found(self, db, mocker):
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=None,
        )

        with pytest.raises(NotFoundError):
            await SettingsService.get_profile(db, USER_ID)


# ---------------------------------------------------------------------------
# update_profile
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_get_profile(mocker):
    """Stub out the refreshed-profile read; we assert inputs, not output shape."""
    response = SettingsProfileResponse(
        profile=ProfileData(first_name="Ada"),
        financial_profile=None,
        brokerage=None,
        linked_accounts=[],
        member_since=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return mocker.patch(
        "app.services.settings.SettingsService.get_profile",
        new_callable=AsyncMock,
        return_value=response,
    )


class TestUpdateProfile:
    async def test_syncs_to_alpaca_when_account_active(
        self, db, alpaca, mocker, stub_get_profile
    ):
        update_fields = mocker.patch(
            "app.services.settings.UserProfileRepository.update_fields",
            new_callable=AsyncMock,
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=_make_brokerage("ACTIVE"),
        )

        await SettingsService.update_profile(
            db,
            USER_ID,
            ProfileUpdateRequest(first_name="Ada", city="Paris"),
            alpaca,
        )

        update_fields.assert_awaited_once_with(
            db, USER_ID, first_name="Ada", city="Paris"
        )
        alpaca.update_account.assert_awaited_once_with(
            ALPACA_ACCOUNT_ID,
            {
                "contact": {"city": "Paris"},
                "identity": {"given_name": "Ada"},
            },
        )

    async def test_skips_alpaca_when_no_active_account(
        self, db, alpaca, mocker, stub_get_profile
    ):
        mocker.patch(
            "app.services.settings.UserProfileRepository.update_fields",
            new_callable=AsyncMock,
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )

        await SettingsService.update_profile(
            db,
            USER_ID,
            ProfileUpdateRequest(city="Paris"),
            alpaca,
        )

        alpaca.update_account.assert_not_called()

    @pytest.mark.parametrize(
        "non_active_status",
        ["SUBMITTED", "APPROVED", "ACTION_REQUIRED", "ACCOUNT_CLOSED", "REJECTED"],
    )
    async def test_skips_alpaca_when_account_not_active(
        self, db, alpaca, mocker, stub_get_profile, non_active_status
    ):
        mocker.patch(
            "app.services.settings.UserProfileRepository.update_fields",
            new_callable=AsyncMock,
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=_make_brokerage(non_active_status),
        )

        await SettingsService.update_profile(
            db,
            USER_ID,
            ProfileUpdateRequest(city="Paris"),
            alpaca,
        )

        alpaca.update_account.assert_not_called()

    async def test_preferred_name_only_skips_alpaca_entirely(
        self, db, alpaca, mocker, stub_get_profile
    ):
        """preferred_name is Sevino-only; Alpaca should never be consulted."""
        mocker.patch(
            "app.services.settings.UserProfileRepository.update_fields",
            new_callable=AsyncMock,
        )
        brokerage_lookup = mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=_make_brokerage("ACTIVE"),
        )

        await SettingsService.update_profile(
            db,
            USER_ID,
            ProfileUpdateRequest(preferred_name="Addie"),
            alpaca,
        )

        brokerage_lookup.assert_not_called()
        alpaca.update_account.assert_not_called()


class TestBuildAlpacaProfileUpdatePayload:
    def test_groups_contact_and_identity(self):
        payload = _build_alpaca_profile_update_payload(
            {
                "first_name": "Ada",
                "middle_name": "Augusta",
                "last_name": "Lovelace",
                "phone_number": "+15551112222",
                "city": "London",
                "postal_code": "10001",
                "preferred_name": "Addie",  # Sevino-only, must not appear
            }
        )
        assert payload == {
            "contact": {
                "phone_number": "+15551112222",
                "city": "London",
                "postal_code": "10001",
            },
            "identity": {
                "given_name": "Ada",
                "middle_name": "Augusta",
                "family_name": "Lovelace",
            },
        }

    def test_empty_dict_yields_empty_payload(self):
        assert _build_alpaca_profile_update_payload({}) == {}

    def test_preferred_name_only_yields_empty_payload(self):
        assert _build_alpaca_profile_update_payload({"preferred_name": "A"}) == {}


# ---------------------------------------------------------------------------
# delete_account
# ---------------------------------------------------------------------------


class TestDeleteAccount:
    @pytest.fixture
    def supabase_admin(self) -> AsyncMock:
        return AsyncMock()

    async def test_cascade_closes_alpaca_deletes_db_and_supabase(
        self, db, alpaca, supabase_admin, mocker
    ):
        profile = _make_profile()
        brokerage = _make_brokerage("ACTIVE")
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=profile,
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        )
        # Attach side-effect calls to a shared parent so we can assert order.
        # Contract: close Alpaca → delete row → commit → delete Supabase user;
        # see docstring on SettingsService.delete_account.
        order = Mock()
        order.attach_mock(alpaca.close_account, "close_account")
        order.attach_mock(db.delete, "delete")
        order.attach_mock(db.commit, "commit")
        order.attach_mock(supabase_admin.delete_user, "delete_user")

        await SettingsService.delete_account(db, USER_ID, alpaca, supabase_admin)

        assert order.mock_calls == [
            call.close_account(ALPACA_ACCOUNT_ID),
            call.delete(profile),
            call.commit(),
            call.delete_user(str(USER_ID)),
        ]

    async def test_missing_profile_raises(
        self, db, alpaca, supabase_admin, mocker
    ):
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=None,
        )

        with pytest.raises(NotFoundError):
            await SettingsService.delete_account(db, USER_ID, alpaca, supabase_admin)

        alpaca.close_account.assert_not_called()
        db.delete.assert_not_called()
        supabase_admin.delete_user.assert_not_called()

    @pytest.mark.parametrize("terminal_status", ["ACCOUNT_CLOSED", "REJECTED"])
    async def test_skips_alpaca_close_on_terminal_status(
        self, db, alpaca, supabase_admin, mocker, terminal_status
    ):
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=_make_profile(),
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=_make_brokerage(terminal_status),
        )

        await SettingsService.delete_account(db, USER_ID, alpaca, supabase_admin)

        alpaca.close_account.assert_not_called()
        db.delete.assert_awaited_once()
        supabase_admin.delete_user.assert_awaited_once_with(str(USER_ID))

    async def test_skips_alpaca_close_when_no_brokerage(
        self, db, alpaca, supabase_admin, mocker
    ):
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=_make_profile(),
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )

        await SettingsService.delete_account(db, USER_ID, alpaca, supabase_admin)

        alpaca.close_account.assert_not_called()
        db.delete.assert_awaited_once()
        supabase_admin.delete_user.assert_awaited_once_with(str(USER_ID))

    @pytest.mark.parametrize(
        "exc",
        [
            SupabaseAdminError("refused", status_code=500),
            SupabaseAdminUnavailableError("refused"),
        ],
        ids=["admin_error", "unavailable_error"],
    )
    async def test_supabase_failure_does_not_raise_and_logs_to_sentry(
        self, db, alpaca, supabase_admin, mocker, exc
    ):
        mocker.patch(
            "app.services.settings.UserProfileRepository.get_by_id",
            new_callable=AsyncMock,
            return_value=_make_profile(),
        )
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )
        supabase_admin.delete_user.side_effect = exc
        capture = mocker.patch(
            "app.services.settings.sentry_sdk.capture_exception"
        )
        scope = MagicMock()
        new_scope = mocker.patch(
            "app.services.settings.sentry_sdk.new_scope"
        )
        new_scope.return_value.__enter__.return_value = scope

        # Must not raise — the DB commit already happened, so we return cleanly
        # and let out-of-band reconciliation pick up the orphan auth.users row.
        await SettingsService.delete_account(db, USER_ID, alpaca, supabase_admin)

        db.commit.assert_awaited()
        capture.assert_called_once()
        # The alert_type tag is what Sentry filters/routes on — protect it from
        # being dropped in a future refactor of the new_scope block.
        scope.set_tag.assert_any_call(
            "alert_type", "supabase_admin_delete_orphaned"
        )


# ---------------------------------------------------------------------------
# close_brokerage_account
# ---------------------------------------------------------------------------


class TestCloseBrokerageAccount:
    @pytest.fixture
    def patched_repos(self, mocker):
        brokerage = _make_brokerage("ACTIVE")
        get_by_user = mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        )
        update_status = mocker.patch(
            "app.services.settings.BrokerageAccountRepository.update_status",
            new_callable=AsyncMock,
        )
        return SimpleNamespace(
            brokerage=brokerage,
            get_by_user=get_by_user,
            update_status=update_status,
        )

    async def test_happy_path_closes_and_updates_status(
        self, db, alpaca, patched_repos
    ):
        await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        alpaca.list_positions.assert_awaited_once_with(ALPACA_ACCOUNT_ID)
        alpaca.list_transfers.assert_awaited_once_with(ALPACA_ACCOUNT_ID)
        alpaca.close_account.assert_awaited_once_with(ALPACA_ACCOUNT_ID)
        patched_repos.update_status.assert_awaited_once_with(
            db, patched_repos.brokerage.id, "ACCOUNT_CLOSED"
        )
        db.commit.assert_awaited()

    async def test_rejects_when_open_positions_exist(
        self, db, alpaca, patched_repos
    ):
        alpaca.list_positions.return_value = [
            {"symbol": "AAPL", "qty": "3"},
            {"symbol": "TSLA", "qty": "1"},
        ]

        with pytest.raises(ConflictError) as exc_info:
            await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        assert exc_info.value.code == "OPEN_POSITIONS"
        assert exc_info.value.detail == {"position_count": 2}
        alpaca.close_account.assert_not_called()
        patched_repos.update_status.assert_not_called()

    async def test_rejects_when_pending_transfer_exists(
        self, db, alpaca, patched_repos
    ):
        pending_status = next(iter(PENDING_TRANSFER_STATUSES))
        alpaca.list_transfers.return_value = [
            {"id": "t1", "status": pending_status},
            {"id": "t2", "status": "COMPLETE"},
        ]

        with pytest.raises(ConflictError) as exc_info:
            await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        assert exc_info.value.code == "PENDING_TRANSFERS"
        assert exc_info.value.detail == {"pending_count": 1}
        alpaca.close_account.assert_not_called()

    async def test_rejects_when_cash_balance_non_zero(
        self, db, alpaca, patched_repos
    ):
        # Minimal payload — the non-zero-cash blocker only reads `cash`. Other
        # keys are intentionally omitted so this test can't accidentally start
        # depending on _ACCOUNT_VALUE_FIELDS if those checks get consolidated.
        alpaca.get_trading_account.return_value = {
            "id": ALPACA_ACCOUNT_ID,
            "cash": "670.50",
        }

        with pytest.raises(ConflictError) as exc_info:
            await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        assert exc_info.value.code == "NON_ZERO_BALANCE"
        assert exc_info.value.detail == {"cash_balance": "670.50"}
        alpaca.close_account.assert_not_called()

    @pytest.mark.parametrize("missing_status", [None, "SUBMITTED", "ACCOUNT_CLOSED"])
    async def test_raises_not_found_when_brokerage_missing_or_inactive(
        self, db, alpaca, mocker, missing_status
    ):
        brokerage = None if missing_status is None else _make_brokerage(missing_status)
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        )

        with pytest.raises(NotFoundError):
            await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        alpaca.list_positions.assert_not_called()
        alpaca.close_account.assert_not_called()

    async def test_cash_field_missing_surfaces_alpaca_error(
        self, db, alpaca, patched_repos
    ):
        alpaca.get_trading_account.return_value = {"id": ALPACA_ACCOUNT_ID}

        with pytest.raises(AlpacaBrokerError) as exc_info:
            await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        assert exc_info.value.status_code == 502
        alpaca.close_account.assert_not_called()

    async def test_cash_field_unparseable_surfaces_alpaca_error(
        self, db, alpaca, patched_repos
    ):
        alpaca.get_trading_account.return_value = {
            "id": ALPACA_ACCOUNT_ID,
            "cash": "N/A",
        }

        with pytest.raises(AlpacaBrokerError) as exc_info:
            await SettingsService.close_brokerage_account(db, USER_ID, alpaca)

        assert exc_info.value.status_code == 502
        alpaca.close_account.assert_not_called()


# ---------------------------------------------------------------------------
# get_account_value
# ---------------------------------------------------------------------------


class TestGetAccountValue:
    async def test_returns_mapped_fields(self, db, alpaca, mocker):
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=_make_brokerage("ACTIVE"),
        )
        alpaca.get_trading_account.return_value = {
            "id": ALPACA_ACCOUNT_ID,
            "equity": "10234.56",
            "cash": "1234.56",
            "buying_power": "2469.12",
            "portfolio_value": "10234.56",
        }

        result = await SettingsService.get_account_value(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.equity == "10234.56"
        assert result.cash == "1234.56"
        assert result.buying_power == "2469.12"
        assert result.portfolio_value == "10234.56"

    async def test_missing_brokerage_raises_not_found(self, db, alpaca, mocker):
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=None,
        )

        with pytest.raises(NotFoundError):
            await SettingsService.get_account_value(
                db, alpaca=alpaca, user_id=USER_ID
            )

        alpaca.get_trading_account.assert_not_called()

    async def test_missing_alpaca_fields_raise_alpaca_error(
        self, db, alpaca, mocker
    ):
        mocker.patch(
            "app.services.settings.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=_make_brokerage("ACTIVE"),
        )
        alpaca.get_trading_account.return_value = {"equity": "100.00"}

        with pytest.raises(AlpacaBrokerError) as exc_info:
            await SettingsService.get_account_value(
                db, alpaca=alpaca, user_id=USER_ID
            )

        assert exc_info.value.status_code == 502
        assert set(exc_info.value.detail["missing"]) == {
            "cash",
            "buying_power",
            "portfolio_value",
        }
