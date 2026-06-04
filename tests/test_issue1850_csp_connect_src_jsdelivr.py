"""Regression coverage: offline deployments must not allow jsDelivr by default."""

import re
from pathlib import Path

_HELPERS_PY = Path(__file__).resolve().parents[1] / "api/helpers.py"


def _helpers_src() -> str:
    return _HELPERS_PY.read_text(encoding="utf-8")


class TestCSPConnectSrcOffline:
    def test_connect_src_excludes_jsdelivr(self):
        src = _helpers_src()
        connect_match = re.search(r"connect-src\s+([^;]+);", src)
        assert connect_match, "connect-src directive must exist in CSP"
        assert "https://cdn.jsdelivr.net" not in connect_match.group(1)

    def test_connect_src_still_includes_self(self):
        src = _helpers_src()
        connect_match = re.search(r"connect-src\s+([^;]+);", src)
        assert connect_match, "connect-src directive must exist in CSP"
        assert "'self'" in connect_match.group(1)
