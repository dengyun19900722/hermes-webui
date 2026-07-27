"""Tests for RBAC usage of the existing audit module.

Existing api/audit.py uses jsonl + async flush + search(). These tests
verify that the RBAC actions can be recorded and retrieved via the
existing API surface (write / search / count).

For test isolation we use a temp audit dir by setting AUDIT_DIR via
monkeypatch on the underlying helpers.
"""
import json
import pytest
from pathlib import Path


@pytest.fixture
def isolated_audit(tmp_path, monkeypatch):
    """Redirect audit dir to tmp_path.audits so tests don't touch real logs."""
    audit_dir = tmp_path / "audits"
    audit_dir.mkdir()
    # Patch both the symbol used by _ensure_audit_dir and the helpers
    monkeypatch.setattr("api.audit.AUDIT_DIR", audit_dir)
    monkeypatch.setattr("api.audit._ensure_audit_dir", lambda: audit_dir)
    return audit_dir


def _flush_all():
    """Force any buffered entries to disk before reading."""
    from api.audit import flush
    flush()


def test_write_rbac_event(isolated_audit):
    from api.audit import write, count
    write(category="rbac", action="user.create",
          actor_id="admin1", actor_name="admin",
          target_id="u2", target_name="bob")
    _flush_all()
    # count() walks today's file directly
    total = count(category="rbac")
    assert total >= 1


def test_write_and_search_rbac_event(isolated_audit):
    from api.audit import write, search, count
    write(category="rbac", action="session.share",
          actor_id="alice", actor_name="alice",
          target_id="s1", target_name="s1",
          details={"to_user_id": "bob"})
    _flush_all()
    results = search(category="rbac", limit=10)
    assert len(results) >= 1
    e = results[0]
    assert e["category"] == "rbac"
    assert e["action"] == "session.share"
    assert e["actor_id"] == "alice"
    assert e["details"]["to_user_id"] == "bob"


def test_search_filter_by_action_keyword(isolated_audit):
    from api.audit import write, search
    write(category="rbac", action="user.create")
    write(category="rbac", action="doc.rate")
    write(category="rbac", action="user.create")
    _flush_all()
    results = search(category="rbac", keyword="user.create", limit=10)
    # keyword 是子串搜索，"user.create" 出现在前两条
    matched = [r for r in results if r.get("action") == "user.create"]
    assert len(matched) >= 2


def test_search_limit(isolated_audit):
    from api.audit import write, search
    for i in range(15):
        write(category="rbac", action="test.event", idx=i)
    _flush_all()
    results = search(category="rbac", limit=5)
    assert len(results) == 5


def test_write_includes_actor_metadata(isolated_audit):
    from api.audit import write, search
    write(category="rbac", action="auth.login",
          actor_id="alice", actor_name="alice",
          client_ip="192.168.1.100")
    _flush_all()
    results = search(category="rbac", limit=1)
    assert len(results) == 1
    e = results[0]
    assert e["actor_id"] == "alice"
    assert e["actor_name"] == "alice"
    # client_ip 会被 _anonymize_ip 处理; 只验证字段存在
    assert "client_ip" in e


def test_write_multiple_categories_isolated(isolated_audit):
    """rbac 类目不应与 http 类目混淆。"""
    from api.audit import write, search
    write(category="http", action="GET /api/x")
    write(category="rbac", action="user.create")
    _flush_all()
    rbac_results = search(category="rbac", limit=10)
    assert all(r["category"] == "rbac" for r in rbac_results)
    assert len(rbac_results) == 1
    assert rbac_results[0]["action"] == "user.create"