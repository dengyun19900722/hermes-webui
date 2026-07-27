"""Verify login.js was updated to support username + password auth."""
from pathlib import Path


_LOGIN_JS = Path("static") / "login.js"


def test_login_js_exists():
    assert _LOGIN_JS.exists()


def test_login_js_has_username_field():
    """login.js 必须引用 username 字段（无论是 querySelector 还是 getElementById）。"""
    src = _LOGIN_JS.read_text(encoding="utf-8")
    # login.js 通过 getElementById('username') 读取 username 字段
    # 该字段由 routes.py 渲染的 HTML 模板提供
    assert "username" in src, (
        "login.js must reference the username field (via getElementById or querySelector)"
    )


def test_login_js_keeps_password_field():
    src = _LOGIN_JS.read_text(encoding="utf-8")
    assert "password" in src.lower()


def test_login_js_posts_username_password_to_login_endpoint():
    src = _LOGIN_JS.read_text(encoding="utf-8")
    # 必须包含 endpoint 和 username/password 字段发送
    # (login.js 用相对路径 'api/auth/login')
    assert "auth/login" in src
    assert "username" in src and "password" in src


def test_login_js_init_status_route_check():
    """login.js 启动时应检查 init_status 来决定下一步。"""
    src = _LOGIN_JS.read_text(encoding="utf-8")
    assert "/api/auth/init_status" in src, (
        "login.js must check init_status on startup to route to /setup or login form"
    )


def test_login_js_handles_init_status_response():
    """应根据 init_status 响应决定 redirect 到 /setup 还是显示登录表单。"""
    src = _LOGIN_JS.read_text(encoding="utf-8")
    # 应该 redirect 到 /setup 当未初始化
    assert "/setup" in src


def test_login_js_handles_401_error():
    """401 响应应显示登录错误提示。"""
    src = _LOGIN_JS.read_text(encoding="utf-8")
    # 检查 401 错误处理或错误显示逻辑
    has_401 = "401" in src
    has_error = "error" in src.lower() or "err" in src.lower()
    assert has_401 or has_error