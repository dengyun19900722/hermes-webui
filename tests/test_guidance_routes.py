"""Tests for guidance routes registered via register_guidance_routes().

Requires Flask (项目本身使用自定义 HTTP handler，本测试仅作为可选 route 单元测试).
"""
import io
import pytest

flask = pytest.importorskip("flask", reason="Flask not installed; route tests skipped")

# 解析 fixtures 路径
FIXTURES_DIR = None  # 在 conftest-like setup 中由 progress 测试共享


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect ~/.hermes to tmp_path for isolation."""
    from api import guidance_progress as gp
    fake_home = tmp_path / "hermes"
    fake_home.mkdir()
    monkeypatch.setattr(gp, "get_active_hermes_home", lambda: fake_home)
    return fake_home


@pytest.fixture
def fixtures_dir():
    """Lazy import to avoid pytest order issues."""
    from pathlib import Path
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def app_with_admin(tmp_home):
    """Create a minimal Flask app with admin session for route testing."""
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = "test-secret"
    from api.routes import register_guidance_routes
    register_guidance_routes(app)
    return app


@pytest.fixture
def client(app_with_admin):
    return app_with_admin.test_client()


def _login_as(client, role="admin", username="alice"):
    with client.session_transaction() as sess:
        sess["user"] = {"username": username, "role": role}


def test_get_endpoint_admin_allowed(client):
    _login_as(client, "admin")
    res = client.get("/api/guidance/implementation")
    assert res.status_code == 200
    data = res.get_json()
    assert "tasks" in data
    assert len(data["tasks"]) == 12


def test_get_endpoint_ops_allowed(client):
    _login_as(client, "ops")
    res = client.get("/api/guidance/implementation")
    assert res.status_code == 200


def test_get_endpoint_viewer_forbidden(client):
    _login_as(client, "viewer")
    res = client.get("/api/guidance/implementation")
    assert res.status_code == 403


def test_patch_endpoint_admin(client):
    _login_as(client, "admin")
    res = client.patch(
        "/api/guidance/implementation/1.1_fill_entity_table",
        json={"done": True, "note": "已填写"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["task"]["done"] is True


def test_patch_unknown_task_returns_400(client):
    _login_as(client, "admin")
    res = client.patch(
        "/api/guidance/implementation/bogus",
        json={"done": True},
    )
    assert res.status_code == 400


def test_patch_manual_without_note_returns_400(client):
    """手动标记未自动验证的任务且无备注，应返回 400 manual_note_required。"""
    _login_as(client, "admin")
    res = client.patch(
        "/api/guidance/implementation/1.1_fill_entity_table",
        json={"done": True},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "manual_note_required"


def test_post_note_endpoint(client):
    _login_as(client, "admin")
    res = client.post(
        "/api/guidance/implementation/1.3_import_entities/note",
        json={"note": "关联 ZKREQ-130"},
    )
    assert res.status_code == 200
    assert res.get_json()["task"]["note"] == "关联 ZKREQ-130"


def test_get_report_returns_markdown(client):
    _login_as(client, "admin")
    res = client.get("/api/guidance/implementation/report")
    assert res.status_code == 200
    assert "text/markdown" in res.headers["Content-Type"]
    assert "attachment" in res.headers["Content-Disposition"]
    assert "# 实施助手进度报告" in res.get_data(as_text=True)


def test_post_import_happy(client, fixtures_dir):
    _login_as(client, "admin")
    content = (fixtures_dir / "business_entities_valid.csv").read_bytes()
    res = client.post(
        "/api/guidance/implementation/import-business-entities",
        data={"file": (io.BytesIO(content), "valid.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["imported_rows"] == 5


def test_post_import_validation_error(client, fixtures_dir):
    _login_as(client, "admin")
    content = (fixtures_dir / "business_entities_missing_col.csv").read_bytes()
    res = client.post(
        "/api/guidance/implementation/import-business-entities",
        data={"file": (io.BytesIO(content), "missing.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    data = res.get_json()
    assert "业务线名称" in data["missing"]


def test_no_state_leak_between_profiles(tmp_home, monkeypatch):
    """不同 HERMES_HOME 应读到不同进度."""
    from api import guidance_progress as gp

    other_home = tmp_home / "other"
    other_home.mkdir()
    monkeypatch.setattr(gp, "get_active_hermes_home", lambda: other_home)
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="已填写")

    main_home = tmp_home / "hermes"
    monkeypatch.setattr(gp, "get_active_hermes_home", lambda: main_home)
    state = gp.get_full_state()
    assert state["summary"]["done"] == 0