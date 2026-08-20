import pytest

from app import main


@pytest.fixture(autouse=True)
def legacy_tests_use_demo_user(monkeypatch):
    """Existing endpoint tests predate HTTP auth and exercise demo user #1.

    Authentication and multi-user isolation are covered separately with the
    real middleware enabled in test_auth_users.py.
    """
    monkeypatch.setattr(main, "AUTH_REQUIRED", False)

