"""Teaching-only tests use explicit dependency overrides, never a runtime bypass.

Full cookie/OTP/owner isolation is exercised in tests/auth/test_tutor_auth.py.
"""
from shuxueshuo_server.tutor_demo.api import create_app as protected_app
from shuxueshuo_server.tutor_demo.api import require_tutor_user


def create_app(tutor=None, budget=None):
    app = protected_app(tutor, budget)
    app.dependency_overrides[require_tutor_user] = lambda: {'id': 'teaching-test-student'}
    return app
