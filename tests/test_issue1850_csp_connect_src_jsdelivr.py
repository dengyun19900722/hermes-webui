"""Regression coverage: offline deployments must not allow jsDelivr by default."""

import re

from api.helpers import _build_csp_enforced_policy


def _policy() -> str:
    return _build_csp_enforced_policy(""encoding="utf-8")


class TestCSPConnectSrcOffline:
    def test_connect_src_excludes_jsdelivr(self):
        policy = _policy()
        connect_match = re.search(r"connect-src\s+([^;]+);", policy)
        assert connect_match, "connect-src directive must exist in CSP"
        assert "https://cdn.jsdelivr.net" not in connect_match.group(1)

    def test_connect_src_still_includes_self(self):
        policy = _policy()
        connect_match = re.search(r"connect-src\s+([^;]+);", policy)
        assert connect_match, "connect-src directive must exist in CSP"
        assert "'self'" in connect_match.group(1)
