"""Teaching-only tests use explicit dependency overrides, never a runtime bypass.

Full cookie/OTP/owner isolation is exercised in tests/auth/test_tutor_auth.py.
"""
from shuxueshuo_server.tutor_demo.api import create_app as protected_app
from shuxueshuo_server.tutor_demo.api import require_tutor_user


class TeachingOnlyBudget:
    """Only teaching tests bypass accounting; quota tests use real PostgreSQL."""
    def reserve(self, session_id, *, user_id):
        pass

    def failed(self, session_id):
        pass


def create_app(tutor=None, budget=None):
    app = protected_app(tutor, budget if budget is not None else TeachingOnlyBudget())
    app.dependency_overrides[require_tutor_user] = lambda: {'id': '00000000-0000-0000-0000-000000000001'}
    return app
