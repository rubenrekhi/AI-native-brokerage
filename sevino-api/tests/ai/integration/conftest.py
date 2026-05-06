"""Re-export DB fixtures from tests/integration so AI integration tests can
use the same real-Postgres setup.

pytest discovers fixture functions in any conftest.py at or above a test's
directory; importing the fixture functions here makes them available under
``tests/ai/integration/`` without duplicating the fixture bodies.
"""

from tests.integration.conftest import (  # noqa: F401
    DB_URL,
    TEST_USER_ID,
    _pg_available_sync,
    db_engine,
    db_session,
    insert_auth_user,
    test_user,
)
