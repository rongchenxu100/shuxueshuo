"""Local startup surfaces stale publications without changing or clearing data."""

import pytest

from shuxueshuo_server.product.admin import learning
from shuxueshuo_server.product.config import REPO
from shuxueshuo_server.product.errors import Conflict
from tools.run_site import check_learning_content


@pytest.mark.parametrize("reason", [
    "release.content_version_mismatch", "release.site_content_mismatch",
    "release.site_content_missing",
])
def test_local_startup_warns_when_content_is_stale(monkeypatch, capsys, reason):
    settings = object()

    def verify(actual, site):
        assert actual is settings
        assert site == REPO / "site/knowledge/teaching/version.json"
        raise Conflict(reason)

    monkeypatch.setattr(learning, "verify_release", verify)
    assert check_learning_content(settings) is False
    message = capsys.readouterr().out
    assert "重启服务不会同步内容" in message
    assert "verify-release" in message


def test_local_startup_accepts_matching_content(monkeypatch, capsys):
    monkeypatch.setattr(learning, "verify_release", lambda *_args: {"site": "match"})
    assert check_learning_content(object()) is True
    assert capsys.readouterr().out == ""
