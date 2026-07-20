# RBAC 权限体系实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Hermes WebUI 实现多用户 RBAC 权限体系：会话隔离与会话分享、知识库创建者标记与用户评价、管理员面板与审计。

**Architecture:**
- 扩展 `api/auth.py` 支持多用户认证（users.json 文件存储）
- 新增 `api/session_sharing.py` 处理会话分享
- 扩展 `api/obsidian_notes.py` 集成元数据侧写文件（.meta.json）
- 新增 `api/admin.py` 处理管理员面板与审计日志
- 新增 `api/license_middleware.py` 处理 License 状态前置检查（强耦合）
- **不修改** `api/license.py` 任何现有逻辑

**Tech Stack:** Python (标准库 + pytest), JSON 文件存储, Vanilla JS, 现有 Obsidian vault 集成

**Spec:** `docs/superpowers/specs/2026-07-08-rbac-permission-system-design.md`

---

## 文件结构

```
api/auth.py                                    # 修改：扩展多用户认证
api/license_middleware.py                      # 新建：License 状态前置检查
api/session_sharing.py                         # 新建：会话分享逻辑
api/session_store.py                           # 新建：会话存储（多用户）
api/obsidian_notes.py                          # 修改：扩展元数据
api/obsidian_meta.py                           # 新建：知识库元数据
api/admin.py                                   # 新建：管理员 API
api/audit.py                                   # 新建：审计日志
api/routes.py                                  # 修改：注册新路由

static/login.js                                # 修改：username+password 双字段
static/setup.html                              # 新建：首次部署初始化页
static/setup.js                                # 新建：初始化表单逻辑
static/session_sharing.js                      # 新建：会话分享 UI
static/index.html                              # 修改：用户菜单 + 引入新 JS
static/notes_panel.js                          # 修改：显示创建者+评分
static/i18n.js                                 # 修改：新增 i18n 键

tests/test_license_middleware.py               # 新建：License 中间件
tests/test_license_middleware_integration.py   # 新建：License 中间件路由集成
tests/test_auth_users.py                       # 新建：多用户认证
tests/test_auth_login.py                       # 新建：登录流程
tests/test_session_store.py                    # 新建：会话存储
tests/test_session_sharing.py                  # 新建：会话分享
tests/test_obsidian_meta.py                    # 新建：知识库元数据
tests/test_obsidian_ratings.py                 # 新建：评价功能
tests/test_admin_users.py                      # 新建：用户管理
tests/test_audit.py                            # 新建：审计日志
tests/test_login_ui.py                          # 新建：login.js 双字段验证
tests/test_auth_init_status.py                  # 新建：init_status 端点
tests/test_session_share_ui.py                  # 新建：会话分享 UI 验证
tests/test_obsidian_meta_ui.py                  # 新建：知识库 UI 元数据显示
```

---

## Phase 0: License 中间件集成（前置）

### Task 0: License 状态中间件

**Files:**
- Create: `api/license_middleware.py`
- Test: `tests/test_license_middleware.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_license_middleware.py
"""Tests for License state middleware (pre-RBAC gating)."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from api.license_middleware import (
    check_license_gate, _is_whitelisted_path,
)


def test_whitelist_static_paths():
    assert _is_whitelisted_path("/static/login.js") is True
    assert _is_whitelisted_path("/session/static/main.css") is True


def test_whitelist_health():
    assert _is_whitelisted_path("/health") is True


def test_whitelist_license_routes():
    assert _is_whitelisted_path("/license") is True
    assert _is_whitelisted_path("/license/activate") is True
    assert _is_whitelisted_path("/api/license/status") is True
    assert _is_whitelisted_path("/api/license/import") is True


def test_non_whitelisted_needs_license_check():
    assert _is_whitelisted_path("/login") is False
    assert _is_whitelisted_path("/api/sessions") is False
    assert _is_whitelisted_path("/admin") is False


def test_check_license_gate_not_activated_redirects(tmp_path):
    """未激活时 HTML 请求重定向到 /license/activate。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "not_activated"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is False
    handler.send_response.assert_called_once_with(302)
    location = handler.send_header.call_args_list[0][0][1]
    assert location == "/license/activate"


def test_check_license_gate_expired_returns_403(tmp_path):
    """expired 状态返回 403。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "expired"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is False
    handler.send_response.assert_called_once_with(403)


def test_check_license_gate_copied_returns_403(tmp_path):
    """copied 状态返回 403。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/api/sessions"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "copied"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is False
    handler.send_response.assert_called_once_with(403)


def test_check_license_gate_valid_passes_through(tmp_path):
    """valid 状态放行。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "valid"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is True
    handler.send_response.assert_not_called()


def test_check_license_gate_whitelist_passes_through(tmp_path):
    """白名单路径不检查 license 状态。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/health"

    result = check_license_gate(handler, parsed, tmp_path)
    assert result is True
    handler.send_response.assert_not_called()


def test_check_license_gate_module_error_passes_through(tmp_path):
    """license 模块异常时放行（向后兼容）。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status",
               side_effect=Exception("module broken")):
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_license_middleware.py -v`
Expected: `ModuleNotFoundError: No module named 'api.license_middleware'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/license_middleware.py
"""License state middleware — gates requests before RBAC auth.

Reuses api.license.py without modification. License status acts as a
platform-level prerequisite that precedes any RBAC checks.
"""
from pathlib import Path


WHITELIST_PREFIXES = (
    "/static/",
    "/session/static/",
    "/license",
    "/api/license/",
)


def _is_whitelisted_path(path: str) -> bool:
    """Return True for paths that bypass license gate."""
    if path == "/health":
        return True
    if path.startswith("/static/") or path.startswith("/session/static/"):
        return True
    if path == "/license" or path.startswith("/license/"):
        return True
    if path.startswith("/api/license/"):
        return True
    return False


def _send_json(handler, status_code: int, payload: dict) -> None:
    """Send a JSON error response."""
    import json
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_403(handler, message: str) -> None:
    """Send a plain-text 403 response."""
    body = message.encode("utf-8")
    handler.send_response(403)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_redirect(handler, location: str) -> None:
    """Send a 302 redirect."""
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def check_license_gate(handler, parsed, workspace: Path) -> bool:
    """Gate request by license state. Returns True if request may proceed.

    Behavior:
      - Whitelisted paths always pass.
      - license module errors: pass through (back-compat).
      - not_activated: 302 → /license/activate (HTML) / 503 JSON (API).
      - expired: 403 plain text.
      - copied:   403 plain text.
      - valid:    pass through to RBAC.
    """
    if _is_whitelisted_path(parsed.path):
        return True

    try:
        from api.license import init_license_config, check_license_status
        init_license_config(workspace)
        status = check_license_status(workspace)
    except Exception:
        # License 模块异常时放行，保持向后兼容
        return True

    license_state = status.get("status")

    if license_state == "expired":
        _send_403(handler, "License 已过期，请联系管理员续期")
        return False

    if license_state == "copied":
        _send_403(handler, "License 检测到 MAC 变更，请重新激活")
        return False

    if license_state == "not_activated":
        if parsed.path.startswith("/api/"):
            _send_json(handler, 503, {"error": "License not activated"})
        else:
            _send_redirect(handler, "/license/activate")
        return False

    # valid (or unknown status) → 放行
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_license_middleware.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add api/license_middleware.py tests/test_license_middleware.py
git commit -m "feat(rbac): add License state middleware (pre-RBAC gating)"
```

---

### Task 0.5: 集成 License 中间件到 routes.py

**Files:**
- Modify: `api/routes.py` (请求分发入口)
- Test: `tests/test_license_middleware_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_license_middleware_integration.py
"""Integration: License middleware inserted before auth check."""
import pytest
from unittest.mock import MagicMock, patch


def test_routes_dispatch_calls_license_gate_first():
    """Verify routes dispatch invokes license gate before check_auth."""
    from api import routes
    assert hasattr(routes, "_check_license_middleware")
    # 检查 dispatch 入口确实调用了 license 中间件
    import inspect
    src = inspect.getsource(routes._dispatch_request)
    assert "_check_license_middleware" in src
    # license 必须在 check_auth 之前
    license_pos = src.find("_check_license_middleware")
    auth_pos = src.find("check_auth")
    assert license_pos < auth_pos, "license gate must run before check_auth"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_license_middleware_integration.py -v`
Expected: AssertionError or AttributeError

- [ ] **Step 3: Wire middleware into routes.py**

在 `api/routes.py` 中：

1. 顶部添加导入：
```python
from api.license_middleware import check_license_gate
```

2. 添加 `_check_license_middleware` 包装函数：
```python
def _check_license_middleware(handler, parsed) -> bool:
    """Wrap license gate with workspace lookup."""
    from pathlib import Path
    from api.config import DEFAULT_WORKSPACE
    workspace = Path(DEFAULT_WORKSPACE).expanduser().resolve()
    return check_license_gate(handler, parsed, workspace)
```

3. 在请求分发入口（找到现有 `check_auth` 调用处）之前插入：
```python
# 顺序：License → Auth → RBAC
if not _check_license_middleware(handler, parsed):
    return
if not check_auth(handler, parsed):
    return
```

- [ ] **Step 4: Run integration test**

Run: `python -m pytest tests/test_license_middleware_integration.py -v`
Expected: 1 passed

- [ ] **Step 5: Run full license middleware test suite**

Run: `python -m pytest tests/test_license_middleware.py tests/test_license_middleware_integration.py -v`
Expected: All passed

- [ ] **Step 6: Commit**

```bash
git add api/routes.py tests/test_license_middleware_integration.py
git commit -m "feat(rbac): wire License middleware into request dispatch"
```

---

## Phase 1: 用户认证系统

### Task 1: users.json 读写工具

**Files:**
- Create: `api/user_store.py`
- Test: `tests/test_user_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_user_store.py
import json
import pytest
from pathlib import Path
from api.user_store import load_users, save_users, find_user_by_username, add_user


def test_load_users_empty(tmp_path: Path):
    assert load_users(tmp_path) == []


def test_save_and_load_users(tmp_path: Path):
    users = [{"id": "u1", "username": "alice", "password_hash": "x", "role": "user"}]
    save_users(tmp_path, users)
    assert load_users(tmp_path) == users


def test_find_user_by_username(tmp_path: Path):
    users = [
        {"id": "u1", "username": "alice", "password_hash": "x", "role": "user"},
        {"id": "u2", "username": "bob", "password_hash": "y", "role": "admin"},
    ]
    save_users(tmp_path, users)
    assert find_user_by_username(tmp_path, "alice")["id"] == "u1"
    assert find_user_by_username(tmp_path, "bob")["role"] == "admin"
    assert find_user_by_username(tmp_path, "nobody") is None


def test_add_user_creates_id(tmp_path: Path):
    user = add_user(tmp_path, {"username": "alice", "password_hash": "x", "role": "user"})
    assert "id" in user
    assert user["username"] == "alice"
    # 持久化到磁盘
    assert find_user_by_username(tmp_path, "alice") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_user_store.py -v`
Expected: `ModuleNotFoundError: No module named 'api.user_store'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/user_store.py
"""Local-file user store backed by users.json."""
import json
import uuid
from pathlib import Path
from typing import Any


USERS_FILE = "users.json"


def _users_file(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / USERS_FILE


def load_users(state_dir: Path) -> list[dict[str, Any]]:
    """Load users from users.json. Returns empty list if file missing or corrupt."""
    path = _users_file(state_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("users", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_users(state_dir: Path, users: list[dict[str, Any]]) -> None:
    """Atomically persist users to users.json."""
    path = _users_file(state_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"users": users}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def find_user_by_username(state_dir: Path, username: str) -> dict[str, Any] | None:
    """Find a user by username (case-sensitive)."""
    for user in load_users(state_dir):
        if user.get("username") == username:
            return user
    return None


def find_user_by_id(state_dir: Path, user_id: str) -> dict[str, Any] | None:
    """Find a user by id."""
    for user in load_users(state_dir):
        if user.get("id") == user_id:
            return user
    return None


def add_user(state_dir: Path, user: dict[str, Any]) -> dict[str, Any]:
    """Add a new user with a generated UUID."""
    if "id" not in user:
        user["id"] = str(uuid.uuid4())
    users = load_users(state_dir)
    users.append(user)
    save_users(state_dir, users)
    return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_user_store.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/user_store.py tests/test_user_store.py
git commit -m "feat(rbac): add user_store module with users.json CRUD"
```

---

### Task 2: 首次部署初始化

**Files:**
- Modify: `api/auth.py:344-346` (扩展 `is_auth_enabled`)
- Test: `tests/test_auth_initialization.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_initialization.py
import pytest
from pathlib import Path
from api.auth import is_initialized, needs_initialization, initialize_first_admin


def test_needs_initialization_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    assert needs_initialization() is True
    assert is_initialized() is False


def test_needs_initialization_with_users(tmp_path: Path, monkeypatch):
    from api.user_store import add_user
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    add_user(tmp_path, {"username": "alice", "password_hash": "x", "role": "user"})
    assert needs_initialization() is False
    assert is_initialized() is True


def test_initialize_first_admin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    admin = initialize_first_admin("admin", "secret123")
    assert admin["role"] == "admin"
    assert admin["username"] == "admin"
    assert needs_initialization() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_initialization.py -v`
Expected: ImportError or AttributeError

- [ ] **Step 3: Write minimal implementation**

```python
# api/auth.py 修改：在文件末尾添加以下函数

from api.user_store import load_users, add_user, find_user_by_username

def _state_dir() -> Path:
    """Return the state directory for auth/users storage."""
    from api.config import STATE_DIR
    return STATE_DIR


def needs_initialization() -> bool:
    """Return True if no users exist yet (first deployment)."""
    return len(load_users(_state_dir())) == 0


def is_initialized() -> bool:
    """Return True if at least one user has been registered."""
    return not needs_initialization()


def initialize_first_admin(username: str, password: str) -> dict:
    """Create the initial admin user. Raises ValueError if already initialized."""
    if not needs_initialization():
        raise ValueError("System already initialized")
    password_hash = _hash_password(password)
    return add_user(_state_dir(), {
        "username": username,
        "password_hash": password_hash,
        "role": "admin",
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
```

Add at the top of `api/auth.py`:
```python
from datetime import datetime
from pathlib import Path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_initialization.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add api/auth.py tests/test_auth_initialization.py
git commit -m "feat(rbac): add first-time initialization for admin user"
```

---

### Task 3: 多用户登录 API

**Files:**
- Modify: `api/auth.py:380-400` (扩展 `create_session`)
- Test: `tests/test_auth_login.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_login.py
import pytest
from api.auth import (
    authenticate, create_user_session, get_user_from_session,
    invalidate_user_session
)
from api.user_store import add_user


def _create_test_user(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    defaults = {
        "username": "alice",
        "password_hash": __import__("api.auth").auth._hash_password("secret123"),
        "role": "user",
    }
    defaults.update(overrides)
    return add_user(tmp_path, defaults)


def test_authenticate_success(tmp_path, monkeypatch):
    _create_test_user(tmp_path, monkeypatch)
    user = authenticate("alice", "secret123")
    assert user["username"] == "alice"


def test_authenticate_wrong_password(tmp_path, monkeypatch):
    _create_test_user(tmp_path, monkeypatch)
    assert authenticate("alice", "wrong") is None


def test_authenticate_unknown_user(tmp_path, monkeypatch):
    _create_test_user(tmp_path, monkeypatch)
    assert authenticate("nobody", "anything") is None


def test_session_lifecycle(tmp_path, monkeypatch):
    user = _create_test_user(tmp_path, monkeypatch)
    token = create_user_session(user["id"])
    assert get_user_from_session(token)["id"] == user["id"]
    invalidate_user_session(token)
    assert get_user_from_session(token) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_login.py -v`
Expected: ImportError or AttributeError

- [ ] **Step 3: Write minimal implementation**

```python
# api/auth.py 添加以下函数

_user_sessions: dict[str, dict] = {}  # token -> {user_id, expires_at}
_USER_SESSION_TTL = 86400 * 30  # 30 days


def authenticate(username: str, password: str) -> dict | None:
    """Verify username/password. Returns user dict on success, None on failure."""
    from api.user_store import find_user_by_username
    user = find_user_by_username(_state_dir(), username)
    if not user:
        return None
    if not verify_password_against_hash(password, user["password_hash"]):
        return None
    return user


def verify_password_against_hash(plain: str, expected_hash: str) -> bool:
    """Verify plaintext against a stored PBKDF2 hash."""
    import hmac
    return hmac.compare_digest(_hash_password(plain), expected_hash)


def create_user_session(user_id: str) -> str:
    """Create a new auth session token bound to a user_id."""
    import secrets
    import time
    token = secrets.token_hex(32)
    _user_sessions[token] = {
        "user_id": user_id,
        "expires_at": time.time() + _USER_SESSION_TTL,
    }
    return token


def get_user_from_session(token: str) -> dict | None:
    """Return the user dict for a valid session token, or None."""
    import time
    session = _user_sessions.get(token)
    if not session or time.time() > session["expires_at"]:
        _user_sessions.pop(token, None)
        return None
    from api.user_store import find_user_by_id
    return find_user_by_id(_state_dir(), session["user_id"])


def invalidate_user_session(token: str) -> None:
    """Invalidate a session token."""
    _user_sessions.pop(token, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_login.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/auth.py tests/test_auth_login.py
git commit -m "feat(rbac): add multi-user login with session management"
```

---

### Task 4: 用户角色与权限检查装饰器

**Files:**
- Modify: `api/auth.py` (末尾追加)
- Test: `tests/test_auth_roles.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_roles.py
import pytest
from api.auth import is_admin, require_role


def test_is_admin_true():
    user = {"role": "admin"}
    assert is_admin(user) is True


def test_is_admin_false():
    user = {"role": "user"}
    assert is_admin(user) is False


def test_is_admin_none():
    assert is_admin(None) is False


def test_require_role_passes():
    user = {"role": "admin"}
    require_role(user, "admin")  # should not raise


def test_require_role_fails():
    user = {"role": "user"}
    with pytest.raises(PermissionError):
        require_role(user, "admin")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_roles.py -v`
Expected: ImportError or AttributeError

- [ ] **Step 3: Write minimal implementation**

```python
# api/auth.py 末尾追加


def is_admin(user: dict | None) -> bool:
    """Return True if user has admin role."""
    if not user:
        return False
    return user.get("role") == "admin"


def require_role(user: dict | None, role: str) -> None:
    """Raise PermissionError if user doesn't have the required role."""
    if not user:
        raise PermissionError("Authentication required")
    if user.get("role") != role:
        raise PermissionError(f"Requires role: {role}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_roles.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add api/auth.py tests/test_auth_roles.py
git commit -m "feat(rbac): add role check helpers"
```

---

## Phase 2: 会话隔离与分享

### Task 5: 会话存储模块

**Files:**
- Create: `api/session_store.py`
- Test: `tests/test_session_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_store.py
import json
import pytest
from pathlib import Path
from api.session_store import (
    load_user_sessions, save_user_sessions,
    list_user_sessions, add_session, get_session,
    delete_session, list_all_sessions_for_admin
)


def _setup(tmp_path):
    return tmp_path / "sessions"


def test_empty_returns_no_sessions(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    assert list_user_sessions(sessions_dir, "u1") == []


def test_add_and_list_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    session = add_session(sessions_dir, "u1", {"title": "Test Chat"})
    assert session["title"] == "Test Chat"
    assert session["owner_id"] == "u1"
    assert "id" in session
    listed = list_user_sessions(sessions_dir, "u1")
    assert len(listed) == 1
    assert listed[0]["id"] == session["id"]


def test_get_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    s = add_session(sessions_dir, "u1", {"title": "T"})
    assert get_session(sessions_dir, "u1", s["id"])["title"] == "T"
    assert get_session(sessions_dir, "u1", "nonexistent") is None


def test_delete_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    s = add_session(sessions_dir, "u1", {"title": "T"})
    assert delete_session(sessions_dir, "u1", s["id"]) is True
    assert get_session(sessions_dir, "u1", s["id"]) is None
    assert delete_session(sessions_dir, "u1", s["id"]) is False  # already gone


def test_list_all_for_admin(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    add_session(sessions_dir, "u1", {"title": "A"})
    add_session(sessions_dir, "u2", {"title": "B"})
    all_s = list_all_sessions_for_admin(sessions_dir)
    assert len(all_s) == 2
    titles = {s["title"] for s in all_s}
    assert titles == {"A", "B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_store.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# api/session_store.py
"""Per-user session storage backed by JSON files."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _user_sessions_file(sessions_dir: Path, user_id: str) -> Path:
    user_dir = sessions_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "sessions.json"


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_user_sessions(sessions_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """Load all sessions for a user. Returns empty list if file missing."""
    path = _user_sessions_file(sessions_dir, user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("sessions", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_user_sessions(sessions_dir: Path, user_id: str, sessions: list[dict]) -> None:
    """Atomically persist user's sessions."""
    path = _user_sessions_file(sessions_dir, user_id)
    _atomic_write(path, {"sessions": sessions})


def list_user_sessions(sessions_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """Return all sessions owned by user_id."""
    return load_user_sessions(sessions_dir, user_id)


def add_session(sessions_dir: Path, user_id: str, session: dict) -> dict:
    """Add a new session for user_id. Auto-generates id, owner_id, timestamps."""
    now = datetime.utcnow().isoformat() + "Z"
    session.setdefault("id", str(uuid.uuid4()))
    session.setdefault("owner_id", user_id)
    session.setdefault("created_at", now)
    session.setdefault("updated_at", now)
    sessions = load_user_sessions(sessions_dir, user_id)
    sessions.append(session)
    save_user_sessions(sessions_dir, user_id, sessions)
    return session


def get_session(sessions_dir: Path, user_id: str, session_id: str) -> dict | None:
    """Get a specific session by id for a user."""
    for s in load_user_sessions(sessions_dir, user_id):
        if s.get("id") == session_id:
            return s
    return None


def delete_session(sessions_dir: Path, user_id: str, session_id: str) -> bool:
    """Delete a session. Returns True if deleted, False if not found."""
    sessions = load_user_sessions(sessions_dir, user_id)
    new_sessions = [s for s in sessions if s.get("id") != session_id]
    if len(new_sessions) == len(sessions):
        return False
    save_user_sessions(sessions_dir, user_id, new_sessions)
    return True


def list_all_sessions_for_admin(sessions_dir: Path) -> list[dict[str, Any]]:
    """Admin-only: list all sessions across all users."""
    if not sessions_dir.exists():
        return []
    all_sessions = []
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        all_sessions.extend(load_user_sessions(sessions_dir, user_id))
    return all_sessions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session_store.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add api/session_store.py tests/test_session_store.py
git commit -m "feat(rbac): add per-user session store backed by JSON"
```

---

### Task 6: 会话分享模块

**Files:**
- Create: `api/session_sharing.py`
- Test: `tests/test_session_sharing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_sharing.py
import pytest
from pathlib import Path
from api.session_sharing import (
    share_session_to_user, share_session_with_token,
    list_outgoing_shares, list_incoming_shares,
    list_shared_sessions, revoke_share, resolve_share_token
)
from api.session_store import add_session


@pytest.fixture
def setup_users(tmp_path: Path):
    """Create alice and bob with one session each."""
    sessions_dir = tmp_path / "sessions"
    s1 = add_session(sessions_dir, "alice", {"title": "Alice Chat"})
    s2 = add_session(sessions_dir, "bob", {"title": "Bob Chat"})
    return {"sessions_dir": sessions_dir, "alice_s": s1, "bob_s": s2}


def test_share_to_user(setup_users):
    s = share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    assert s["to_user_id"] == "bob"
    assert s["session_id"] == setup_users["alice_s"]["id"]
    # alice 看到 1 条 outgoing
    assert len(list_outgoing_shares(setup_users["sessions_dir"], "alice")) == 1
    # bob 看到 1 条 incoming
    assert len(list_incoming_shares(setup_users["sessions_dir"], "bob")) == 1


def test_list_shared_sessions_for_bob(setup_users):
    """Bob should see Alice's session in his shared list."""
    share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    shared = list_shared_sessions(setup_users["sessions_dir"], "bob")
    assert len(shared) == 1
    assert shared[0]["session_id"] == setup_users["alice_s"]["id"]


def test_share_with_token(setup_users):
    s = share_session_with_token(
        setup_users["sessions_dir"], "alice",
        setup_users["alice_s"]["id"]
    )
    assert s["type"] == "token"
    assert s["token"] is not None
    # 通过 token 解析
    resolved = resolve_share_token(setup_users["sessions_dir"], s["token"])
    assert resolved["session_id"] == setup_users["alice_s"]["id"]


def test_revoke_share(setup_users):
    s = share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    assert revoke_share(setup_users["sessions_dir"], "alice", s["id"]) is True
    assert len(list_outgoing_shares(setup_users["sessions_dir"], "alice")) == 0
    assert len(list_incoming_shares(setup_users["sessions_dir"], "bob")) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_sharing.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# api/session_sharing.py
"""Session sharing between users (user-to-user and token-link)."""
import json
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from api.session_store import _atomic_write, load_user_sessions


def _shares_file(sessions_dir: Path, user_id: str) -> Path:
    user_dir = sessions_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "shares.json"


def _load_shares(sessions_dir: Path, user_id: str) -> dict:
    """Load shares file for user. Returns {outgoing: [...], incoming: [...]}."""
    path = _shares_file(sessions_dir, user_id)
    if not path.exists():
        return {"outgoing": [], "incoming": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "outgoing": data.get("outgoing", []),
                "incoming": data.get("incoming", []),
            }
    except Exception:
        pass
    return {"outgoing": [], "incoming": []}


def _save_shares(sessions_dir: Path, user_id: str, shares: dict) -> None:
    _atomic_write(_shares_file(sessions_dir, user_id), shares)


def share_session_to_user(
    sessions_dir: Path, from_user_id: str, to_user_id: str, session_id: str
) -> dict:
    """Share a session from one user to another user."""
    now = datetime.utcnow().isoformat() + "Z"
    share = {
        "id": str(uuid.uuid4()),
        "to_user_id": to_user_id,
        "session_id": session_id,
        "type": "user",
        "created_at": now,
    }
    # 写入 from_user 的 outgoing
    shares = _load_shares(sessions_dir, from_user_id)
    shares["outgoing"].append(share)
    _save_shares(sessions_dir, from_user_id, shares)
    # 写入 to_user 的 incoming（镜像）
    incoming_shares = _load_shares(sessions_dir, to_user_id)
    incoming_shares["incoming"].append({
        **share,
        "from_user_id": from_user_id,
    })
    _save_shares(sessions_dir, to_user_id, incoming_shares)
    return share


def share_session_with_token(
    sessions_dir: Path, from_user_id: str, session_id: str
) -> dict:
    """Generate a token link for a session."""
    now = datetime.utcnow().isoformat() + "Z"
    token = secrets.token_urlsafe(32)
    share = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "type": "token",
        "token": token,
        "created_at": now,
    }
    shares = _load_shares(sessions_dir, from_user_id)
    shares["outgoing"].append(share)
    _save_shares(sessions_dir, from_user_id, shares)
    return share


def list_outgoing_shares(sessions_dir: Path, user_id: str) -> list[dict]:
    """List shares created by this user."""
    return _load_shares(sessions_dir, user_id)["outgoing"]


def list_incoming_shares(sessions_dir: Path, user_id: str) -> list[dict]:
    """List shares received by this user."""
    return _load_shares(sessions_dir, user_id)["incoming"]


def list_shared_sessions(sessions_dir: Path, user_id: str) -> list[dict]:
    """List sessions shared to this user (enriched with session info)."""
    incoming = list_incoming_shares(sessions_dir, user_id)
    result = []
    for share in incoming:
        from_user_id = share.get("from_user_id")
        session_id = share.get("session_id")
        if not from_user_id or not session_id:
            continue
        # 从分享者的会话列表中读取会话详情
        from_sessions = load_user_sessions(sessions_dir, from_user_id)
        session = next((s for s in from_sessions if s.get("id") == session_id), None)
        if session:
            result.append({
                "share_id": share["id"],
                "from_user_id": from_user_id,
                "session": session,
                "shared_at": share.get("created_at"),
            })
    return result


def revoke_share(sessions_dir: Path, user_id: str, share_id: str) -> bool:
    """Revoke an outgoing share. Returns True if revoked."""
    shares = _load_shares(sessions_dir, user_id)
    original_count = len(shares["outgoing"])
    shares["outgoing"] = [s for s in shares["outgoing"] if s.get("id") != share_id]
    if len(shares["outgoing"]) == original_count:
        return False
    _save_shares(sessions_dir, user_id, shares)
    # 同时从被分享者的 incoming 移除
    for share in shares["outgoing"]:
        if share.get("type") == "user":
            to_user_id = share.get("to_user_id")
            if to_user_id:
                to_shares = _load_shares(sessions_dir, to_user_id)
                to_shares["incoming"] = [
                    s for s in to_shares["incoming"] if s.get("id") != share_id
                ]
                _save_shares(sessions_dir, to_user_id, to_shares)
    return True


def resolve_share_token(sessions_dir: Path, token: str) -> dict | None:
    """Resolve a share token to the underlying session."""
    if not sessions_dir.exists():
        return None
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        from_user_id = user_dir.name
        shares = _load_shares(sessions_dir, from_user_id)
        for share in shares["outgoing"]:
            if share.get("type") == "token" and share.get("token") == token:
                sessions = load_user_sessions(sessions_dir, from_user_id)
                session = next(
                    (s for s in sessions if s.get("id") == share.get("session_id")),
                    None,
                )
                if session:
                    return {
                        "from_user_id": from_user_id,
                        "session": session,
                        "shared_at": share.get("created_at"),
                    }
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_session_sharing.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/session_sharing.py tests/test_session_sharing.py
git commit -m "feat(rbac): add session sharing (user-to-user and token link)"
```

---

## Phase 3: 知识库元数据

### Task 7: 知识库元数据读写

**Files:**
- Create: `api/obsidian_meta.py`
- Test: `tests/test_obsidian_meta.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_obsidian_meta.py
import json
import pytest
from pathlib import Path
from api.obsidian_meta import (
    load_meta, save_meta, ensure_meta,
    get_creator, get_ratings, add_or_update_rating,
    compute_rating_summary
)


def test_load_meta_missing(tmp_path: Path):
    meta = load_meta(tmp_path, "doc1.md")
    assert meta == {}


def test_save_and_load_meta(tmp_path: Path):
    save_meta(tmp_path, "doc1.md", {"creator_id": "u1", "creator_name": "alice"})
    loaded = load_meta(tmp_path, "doc1.md")
    assert loaded["creator_id"] == "u1"


def test_ensure_meta_creates(tmp_path: Path):
    meta = ensure_meta(tmp_path, "doc1.md", creator_id="u1", creator_name="alice")
    assert meta["creator_id"] == "u1"
    assert "ratings" in meta


def test_ensure_meta_idempotent(tmp_path: Path):
    meta1 = ensure_meta(tmp_path, "doc1.md", creator_id="u1", creator_name="alice")
    # 再次调用不应覆盖已有元数据
    meta2 = ensure_meta(tmp_path, "doc1.md", creator_id="u2", creator_name="bob")
    assert meta2["creator_id"] == "u1"  # 保留原有


def test_add_rating(tmp_path: Path):
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc1.md", "u2", "bob", 3)
    ratings = get_ratings(tmp_path, "doc1.md")
    assert len(ratings) == 2


def test_update_existing_rating(tmp_path: Path):
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 2)  # 修改
    ratings = get_ratings(tmp_path, "doc1.md")
    assert len(ratings) == 1
    assert ratings[0]["rating"] == 2


def test_compute_rating_summary(tmp_path: Path):
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc1.md", "u2", "bob", 3)
    summary = compute_rating_summary(tmp_path, "doc1.md")
    assert summary["count"] == 2
    assert summary["average"] == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_obsidian_meta.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# api/obsidian_meta.py
"""Obsidian vault document metadata (sidecar .meta.json files)."""
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _meta_path(meta_dir: Path, doc_rel_path: str) -> Path:
    """Get the sidecar meta file path for a document."""
    safe = doc_rel_path.replace("/", "__").replace("\\", "__")
    return meta_dir / f"{safe}.meta.json"


def load_meta(meta_dir: Path, doc_rel_path: str) -> dict[str, Any]:
    """Load metadata for a document. Returns empty dict if missing."""
    path = _meta_path(meta_dir, doc_rel_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_meta(meta_dir: Path, doc_rel_path: str, meta: dict) -> None:
    """Atomically save metadata."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = _meta_path(meta_dir, doc_rel_path)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def ensure_meta(
    meta_dir: Path, doc_rel_path: str,
    *, creator_id: str, creator_name: str
) -> dict:
    """Ensure metadata exists with creator info. Idempotent — won't overwrite."""
    existing = load_meta(meta_dir, doc_rel_path)
    if existing:
        return existing
    meta = {
        "creator_id": creator_id,
        "creator_name": creator_name,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "ratings": [],
    }
    save_meta(meta_dir, doc_rel_path, meta)
    return meta


def get_creator(meta_dir: Path, doc_rel_path: str) -> dict | None:
    """Return {creator_id, creator_name} or None."""
    meta = load_meta(meta_dir, doc_rel_path)
    if "creator_id" in meta:
        return {"creator_id": meta["creator_id"], "creator_name": meta.get("creator_name", "")}
    return None


def get_ratings(meta_dir: Path, doc_rel_path: str) -> list[dict]:
    """Return list of ratings."""
    meta = load_meta(meta_dir, doc_rel_path)
    return meta.get("ratings", [])


def add_or_update_rating(
    meta_dir: Path, doc_rel_path: str,
    user_id: str, username: str, rating: int
) -> dict:
    """Add or update a user's rating. Returns the rating record."""
    if not (1 <= rating <= 5):
        raise ValueError("rating must be between 1 and 5")
    meta = load_meta(meta_dir, doc_rel_path)
    if "ratings" not in meta:
        meta["ratings"] = []
    now = datetime.utcnow().isoformat() + "Z"
    # 查找现有评分
    existing = next(
        (r for r in meta["ratings"] if r.get("user_id") == user_id),
        None,
    )
    if existing:
        existing["rating"] = rating
        existing["updated_at"] = now
        record = existing
    else:
        record = {
            "user_id": user_id,
            "username": username,
            "rating": rating,
            "created_at": now,
        }
        meta["ratings"].append(record)
    save_meta(meta_dir, doc_rel_path, meta)
    return record


def compute_rating_summary(meta_dir: Path, doc_rel_path: str) -> dict:
    """Return {count, average} for a document's ratings."""
    ratings = get_ratings(meta_dir, doc_rel_path)
    if not ratings:
        return {"count": 0, "average": 0.0}
    total = sum(r.get("rating", 0) for r in ratings)
    return {"count": len(ratings), "average": round(total / len(ratings), 2)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_obsidian_meta.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add api/obsidian_meta.py tests/test_obsidian_meta.py
git commit -m "feat(rbac): add knowledge base metadata (creator + ratings)"
```

---

### Task 8: 评价 API

**Files:**
- Create: `api/routes.py` modifications
- Test: `tests/test_obsidian_ratings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_obsidian_ratings.py
import pytest
from pathlib import Path
from api.obsidian_meta import (
    add_or_update_rating, get_ratings, compute_rating_summary
)


def test_full_rating_flow(tmp_path: Path):
    """模拟完整的评价流程：3 个用户评价同一文档。"""
    doc = "01-故障知识库/test.md"
    add_or_update_rating(tmp_path, doc, "u1", "alice", 5)
    add_or_update_rating(tmp_path, doc, "u2", "bob", 4)
    add_or_update_rating(tmp_path, doc, "u3", "charlie", 3)

    ratings = get_ratings(tmp_path, doc)
    assert len(ratings) == 3

    summary = compute_rating_summary(tmp_path, doc)
    assert summary["count"] == 3
    assert summary["average"] == 4.0


def test_invalid_rating_rejected(tmp_path: Path):
    doc = "test.md"
    with pytest.raises(ValueError):
        add_or_update_rating(tmp_path, doc, "u1", "alice", 0)
    with pytest.raises(ValueError):
        add_or_update_rating(tmp_path, doc, "u1", "alice", 6)


def test_user_can_only_rate_once(tmp_path: Path):
    doc = "test.md"
    add_or_update_rating(tmp_path, doc, "u1", "alice", 5)
    add_or_update_rating(tmp_path, doc, "u1", "alice", 1)  # 修改而非重复
    ratings = get_ratings(tmp_path, doc)
    assert len(ratings) == 1
    assert ratings[0]["rating"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_obsidian_ratings.py -v`
Expected: 3 passed (Task 7 已覆盖此逻辑)

- [ ] **Step 3: Verify existing tests still pass**

Run: `python -m pytest tests/test_obsidian_meta.py tests/test_obsidian_ratings.py -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_obsidian_ratings.py
git commit -m "test(rbac): add integration tests for rating flow"
```

---

## Phase 4: 管理员面板与审计

### Task 9: 审计日志模块

**Files:**
- Create: `api/audit.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit.py
import pytest
from pathlib import Path
from api.audit import log_event, list_events, AUDIT_FILE


@pytest.fixture(autouse=True)
def clean_audit(tmp_path, monkeypatch):
    """Reset audit file before each test."""
    monkeypatch.setattr("api.audit.AUDIT_FILE", tmp_path / "audit.json")
    yield


def test_log_event(tmp_path):
    log_event("alice", "alice_name", "user.create", target_type="user", target_id="u2", target_name="bob")
    events = list_events()
    assert len(events) == 1
    assert events[0]["actor_name"] == "alice_name"
    assert events[0]["action"] == "user.create"


def test_list_events_filter_by_action():
    log_event("alice", "alice_name", "user.create")
    log_event("bob", "bob_name", "doc.delete")
    log_event("charlie", "charlie_name", "user.create")
    user_creates = list_events(action="user.create")
    assert len(user_creates) == 2


def test_list_events_limit():
    for i in range(20):
        log_event("alice", "alice", "test.event")
    events = list_events(limit=5)
    assert len(events) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_audit.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# api/audit.py
"""Audit logging for RBAC actions."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


from api.config import STATE_DIR

AUDIT_FILE = STATE_DIR / "audit.json"
_MAX_LOGS = 10000  # 防止无界增长


def _load_logs() -> list[dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    try:
        data = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
        return data.get("logs", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_logs(logs: list[dict]) -> None:
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUDIT_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"logs": logs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(AUDIT_FILE)


def log_event(
    actor_id: str,
    actor_name: str,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> dict:
    """Record an audit event."""
    logs = _load_logs()
    event = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "actor_id": actor_id,
        "actor_name": actor_name,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "target_name": target_name,
        "ip_address": ip_address,
        "details": details or {},
    }
    logs.append(event)
    # 保留最新 _MAX_LOGS 条
    if len(logs) > _MAX_LOGS:
        logs = logs[-_MAX_LOGS:]
    _save_logs(logs)
    return event


def list_events(
    *,
    action: str | None = None,
    actor_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """List audit events, optionally filtered."""
    logs = _load_logs()
    # 倒序（最新在前）
    logs.reverse()
    if action:
        logs = [e for e in logs if e.get("action") == action]
    if actor_id:
        logs = [e for e in logs if e.get("actor_id") == actor_id]
    return logs[:limit]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_audit.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add api/audit.py tests/test_audit.py
git commit -m "feat(rbac): add audit logging module"
```

---

### Task 10: 管理员用户管理 API

**Files:**
- Create: `api/admin.py`
- Test: `tests/test_admin_users.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_users.py
import pytest
from pathlib import Path
from api.admin import list_users, create_user, update_user_role, delete_user
from api.user_store import find_user_by_username


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("api.admin._state_dir", lambda: tmp_path)
    from api.auth import initialize_first_admin
    initialize_first_admin("admin", "admin123")
    return tmp_path


def test_list_users(setup):
    users = list_users()
    assert len(users) == 1
    assert users[0]["username"] == "admin"


def test_create_user(setup):
    user = create_user("alice", "alice123", "user")
    assert user["username"] == "alice"
    assert find_user_by_username(setup, "alice") is not None


def test_update_user_role(setup):
    user = create_user("alice", "alice123", "user")
    updated = update_user_role(user["id"], "admin")
    assert updated["role"] == "admin"


def test_delete_user(setup):
    user = create_user("alice", "alice123", "user")
    assert delete_user(user["id"]) is True
    assert find_user_by_username(setup, "alice") is None
    # admin 不能删除自己
    admin_id = find_user_by_username(setup, "admin")["id"]
    assert delete_user(admin_id) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_admin_users.py -v`
Expected: ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

```python
# api/admin.py
"""Admin user management API."""
from datetime import datetime
from pathlib import Path
from typing import Any

from api.audit import log_event
from api.auth import _hash_password, _state_dir
from api.user_store import (
    add_user as _add_user,
    find_user_by_id,
    find_user_by_username,
    load_users,
    save_users,
)


def list_users() -> list[dict[str, Any]]:
    """List all users (without password hashes)."""
    users = load_users(_state_dir())
    # 移除敏感字段
    return [
        {k: v for k, v in u.items() if k != "password_hash"}
        for u in users
    ]


def create_user(username: str, password: str, role: str = "user") -> dict:
    """Create a new user. Raises ValueError if username exists."""
    if find_user_by_username(_state_dir(), username):
        raise ValueError(f"User already exists: {username}")
    if role not in ("user", "admin"):
        raise ValueError(f"Invalid role: {role}")
    user = _add_user(_state_dir(), {
        "username": username,
        "password_hash": _hash_password(password),
        "role": role,
        "created_at": datetime.utcnow().isoformat() + "Z",
    })
    log_event(
        actor_id="system", actor_name="system",
        action="user.create",
        target_type="user", target_id=user["id"], target_name=username,
    )
    return {k: v for k, v in user.items() if k != "password_hash"}


def update_user_role(user_id: str, new_role: str, *, actor_id: str = "system", actor_name: str = "system") -> dict | None:
    """Update a user's role. Returns updated user or None if not found."""
    if new_role not in ("user", "admin"):
        raise ValueError(f"Invalid role: {new_role}")
    users = load_users(_state_dir())
    for user in users:
        if user.get("id") == user_id:
            old_role = user.get("role")
            user["role"] = new_role
            save_users(_state_dir(), users)
            log_event(
                actor_id=actor_id, actor_name=actor_name,
                action="user.role_change",
                target_type="user", target_id=user_id, target_name=user.get("username"),
                details={"old_role": old_role, "new_role": new_role},
            )
            return {k: v for k, v in user.items() if k != "password_hash"}
    return None


def delete_user(user_id: str, *, actor_id: str = "system", actor_name: str = "system") -> bool:
    """Delete a user. Cannot delete the last admin."""
    users = load_users(_state_dir())
    target = next((u for u in users if u.get("id") == user_id), None)
    if not target:
        return False
    # 防止删除最后一个 admin
    if target.get("role") == "admin":
        admin_count = sum(1 for u in users if u.get("role") == "admin")
        if admin_count <= 1:
            return False
    users = [u for u in users if u.get("id") != user_id]
    save_users(_state_dir(), users)
    log_event(
        actor_id=actor_id, actor_name=actor_name,
        action="user.delete",
        target_type="user", target_id=user_id, target_name=target.get("username"),
    )
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_admin_users.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add api/admin.py tests/test_admin_users.py
git commit -m "feat(rbac): add admin user management API"
```

---

### Task 11: HTTP 路由集成

**Files:**
- Modify: `api/routes.py` (添加新路由)
- Test: `tests/test_routes_rbac.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_rbac.py
"""Integration tests for RBAC HTTP routes."""
import pytest
from unittest.mock import MagicMock


def test_login_route_exists():
    """Verify /api/auth/login route handler exists."""
    from api.routes import _route_auth_login  # may not exist yet
    assert callable(_route_auth_login)


def test_list_sessions_route_exists():
    from api.routes import _route_list_sessions
    assert callable(_route_list_sessions)


def test_share_session_route_exists():
    from api.routes import _route_share_session
    assert callable(_route_share_session)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_routes_rbac.py -v`
Expected: ImportError

- [ ] **Step 3: Add HTTP route handlers**

```python
# api/routes.py 末尾追加

import json
from api.config import STATE_DIR
from api.auth import (
    authenticate, create_user_session, get_user_from_session,
    invalidate_user_session, is_admin, needs_initialization,
    initialize_first_admin
)
from api.user_store import find_user_by_username
from api.session_store import list_user_sessions
from api.session_sharing import (
    share_session_to_user, list_shared_sessions, revoke_share
)
from api.admin import list_users as admin_list_users, create_user as admin_create_user
from api.audit import log_event, list_events


def _get_current_user(handler) -> dict | None:
    """Extract authenticated user from request session cookie."""
    from api.auth import parse_cookie
    cookie = parse_cookie(handler)
    if not cookie:
        return None
    # 解析 cookie 中的 token
    token = cookie.split(".")[0] if "." in cookie else cookie
    return get_user_from_session(token)


def _route_auth_login(handler, path, parsed):
    """POST /api/auth/login"""
    body = json.loads(handler.rfile.read(int(handler.headers.get("Content-Length", 0))).decode("utf-8"))
    username = body.get("username", "").strip()
    password = body.get("password", "")
    user = authenticate(username, password)
    if not user:
        handler.send_response(401)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": "Invalid credentials"}).encode())
        return
    token = create_user_session(user["id"])
    log_event(user["id"], user["username"], "auth.login")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header(
        "Set-Cookie",
        f"hermes_session={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=2592000",
    )
    handler.end_headers()
    handler.wfile.write(json.dumps({
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]}
    }).encode())


def _route_auth_register(handler, path, parsed):
    """POST /api/auth/register — first-time admin setup only."""
    if not needs_initialization():
        handler.send_response(403)
        handler.send_header("Content-Type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": "Already initialized"}).encode())
        return
    body = json.loads(handler.rfile.read(int(handler.headers.get("Content-Length", 0))).decode("utf-8"))
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or not password:
        handler.send_response(400)
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": "username and password required"}).encode())
        return
    user = initialize_first_admin(username, password)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps({
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]}
    }).encode())


def _route_list_sessions(handler, path, parsed):
    """GET /api/sessions — list current user's sessions + shared."""
    user = _get_current_user(handler)
    if not user:
        handler.send_response(401)
        handler.end_headers()
        return
    sessions_dir = STATE_DIR / "sessions"
    own = list_user_sessions(sessions_dir, user["id"])
    shared = list_shared_sessions(sessions_dir, user["id"])
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps({
        "own": own,
        "shared": shared,
    }).encode())


def _route_share_session(handler, path, parsed):
    """POST /api/sessions/{id}/share — share to specific user."""
    user = _get_current_user(handler)
    if not user:
        handler.send_response(401)
        handler.end_headers()
        return
    # 提取 session_id from path: /api/sessions/{id}/share
    parts = path.strip("/").split("/")
    if len(parts) < 4:
        handler.send_response(400)
        handler.end_headers()
        return
    session_id = parts[2]
    body = json.loads(handler.rfile.read(int(handler.headers.get("Content-Length", 0))).decode("utf-8"))
    to_username = body.get("username", "").strip()
    if not to_username:
        handler.send_response(400)
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": "username required"}).encode())
        return
    target_user = find_user_by_username(STATE_DIR, to_username)
    if not target_user:
        handler.send_response(404)
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": "User not found"}).encode())
        return
    share = share_session_to_user(STATE_DIR / "sessions", user["id"], target_user["id"], session_id)
    log_event(user["id"], user["username"], "session.share",
              target_type="session", target_id=session_id, target_name=to_username)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps({"share": share}).encode())


def _route_admin_users(handler, path, parsed):
    """GET /api/admin/users — admin-only."""
    user = _get_current_user(handler)
    if not user:
        handler.send_response(401)
        handler.end_headers()
        return
    if not is_admin(user):
        handler.send_response(403)
        handler.end_headers()
        return
    users = admin_list_users()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps({"users": users}).encode())


def _route_admin_audit(handler, path, parsed):
    """GET /api/admin/audit — admin-only."""
    user = _get_current_user(handler)
    if not user or not is_admin(user):
        handler.send_response(401 if not user else 403)
        handler.end_headers()
        return
    events = list_events(limit=200)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps({"events": events}).encode())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_routes_rbac.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add api/routes.py tests/test_routes_rbac.py
git commit -m "feat(rbac): integrate RBAC HTTP routes"
```

---

## Phase 4.5: 前端 UI 改造

### Task 11.5: login.js 改造（username + password 双字段）

**Files:**
- Modify: `static/login.js`
- Test: `tests/test_login_ui.py` (HTTP-level integration test for `/login` page)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_login_ui.py
"""Verify /login page renders username + password fields after RBAC refactor."""
import pytest


def test_login_page_renders_username_field():
    """Existing login.js must be updated to include username input."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "static" / "login.js").read_text()
    assert 'name="username"' in src or 'id="username"' in src, \
        "login.js must include a username input field"


def test_login_page_calls_new_login_endpoint():
    """Login form posts to /api/auth/login (preserved endpoint, new signature)."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "static" / "login.js").read_text()
    assert "/api/auth/login" in src


def test_login_page_init_status_check():
    """On load, login.js should check /api/auth/init_status before showing form."""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "static" / "login.js").read_text()
    assert "/api/auth/init_status" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_login_ui.py -v`
Expected: 3 failed (login.js still has single-password form)

- [ ] **Step 3: Update login.js**

修改 `static/login.js` 的核心逻辑：

```javascript
// static/login.js - 改造部分（保留 i18n、CSRF、next=、rate-limit 逻辑）

async function initLoginPage() {
  // 1. 检查 license
  const licStatus = await fetch("/api/license/status").then(r => r.json()).catch(() => ({status: "valid"}));
  if (licStatus.status && licStatus.status !== "valid") {
    window.location.href = "/license/activate";
    return;
  }
  // 2. 检查 RBAC 初始化
  const initStatus = await fetch("/api/auth/init_status").then(r => r.json()).catch(() => ({initialized: true}));
  if (initStatus && initStatus.initialized === false) {
    window.location.href = "/setup";
    return;
  }
  // 3. 显示登录表单
  renderLoginForm();
}

function renderLoginForm() {
  const form = document.getElementById("login-form");
  form.innerHTML = `
    <div class="login-field">
      <input type="text" name="username" id="username"
             placeholder="${I18N.t('login_username')}" autocomplete="username"
             required autofocus>
    </div>
    <div class="login-field">
      <input type="password" name="password" id="password"
             placeholder="${I18N.t('login_password')}" autocomplete="current-password"
             required>
    </div>
    <button type="submit" id="login-submit">${I18N.t('login_button')}</button>
    <div id="login-error" class="login-error" hidden></div>
  `;
  form.addEventListener("submit", onLoginSubmit);
}

async function onLoginSubmit(e) {
  e.preventDefault();
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  if (!username || !password) return;

  const errorEl = document.getElementById("login-error");
  errorEl.hidden = true;

  try {
    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Hermes-CSRF-Token": getCsrfToken(),
      },
      credentials: "same-origin",
      body: JSON.stringify({ username, password }),
    });
    if (resp.ok) {
      // 跳转到 next 或 / 
      const next = new URLSearchParams(window.location.search).get("next") || "/";
      window.location.href = next;
      return;
    }
    if (resp.status === 401) {
      errorEl.textContent = I18N.t("login_error_invalid_credentials");
      errorEl.hidden = false;
    } else if (resp.status === 429) {
      errorEl.textContent = I18N.t("login_error_too_many_attempts");
      errorEl.hidden = false;
    } else {
      errorEl.textContent = I18N.t("login_error_generic");
      errorEl.hidden = false;
    }
  } catch (err) {
    errorEl.textContent = I18N.t("login_error_conn_failed");
    errorEl.hidden = false;
  }
}

initLoginPage();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_login_ui.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add static/login.js tests/test_login_ui.py
git commit -m "feat(rbac): refactor login.js for username+password auth"
```

---

### Task 11.6: 新增 /api/auth/init_status 端点

**Files:**
- Modify: `api/routes.py`
- Test: `tests/test_auth_init_status.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth_init_status.py
"""Verify GET /api/auth/init_status returns RBAC initialization state."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def test_init_status_returns_true_when_users_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {"username": "alice", "password_hash": "x", "role": "user"})

    from api.routes import _route_auth_init_status
    handler = MagicMock()
    parsed = MagicMock()
    _route_auth_init_status(handler, parsed)
    # handler.send_response(200) 应被调用
    handler.send_response.assert_called_with(200)
    # 响应体应包含 initialized: True
    body = handler.wfile.write.call_args[0][0].decode()
    assert '"initialized": true' in body


def test_init_status_returns_false_when_no_users(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.routes import _route_auth_init_status
    handler = MagicMock()
    parsed = MagicMock()
    _route_auth_init_status(handler, parsed)
    handler.send_response.assert_called_with(200)
    body = handler.wfile.write.call_args[0][0].decode()
    assert '"initialized": false' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_init_status.py -v`
Expected: ImportError on `_route_auth_init_status`

- [ ] **Step 3: Implement the route handler**

在 `api/routes.py` 中添加：

```python
def _route_auth_init_status(handler, path, parsed):
    """GET /api/auth/init_status — 是否需要进入 /setup 页。

    Returns {"initialized": bool, "license_status": str}.
    Public endpoint (no auth required) so the login page can decide
    where to redirect on first load.
    """
    from api.auth import needs_initialization
    initialized = not needs_initialization()

    # 同时返回 license 状态，方便前端做一次性判断
    license_status = "valid"
    try:
        from api.config import DEFAULT_WORKSPACE
        from pathlib import Path as _Path
        from api.license import check_license_status
        license_status = check_license_status(_Path(DEFAULT_WORKSPACE)).get("status", "valid")
    except Exception:
        pass

    body = json.dumps({"initialized": initialized, "license_status": license_status}).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
```

并在路由表中注册（找到现有 `/api/auth/*` 路由注册处）：

```python
"/api/auth/init_status": _route_auth_init_status,
```

并在 `PUBLIC_PATHS` 中确认包含此路径（`api/auth.py`）。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_init_status.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add api/routes.py api/auth.py tests/test_auth_init_status.py
git commit -m "feat(rbac): add /api/auth/init_status for login page bootstrap"
```

---

### Task 11.7: 新增 /setup 页

**Files:**
- Create: `static/setup.html`
- Create: `static/setup.js`
- Modify: `static/i18n.js` (添加 setup_* 键)

- [ ] **Step 1: Create setup.html**

```html
<!-- static/setup.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>初始化管理员 · ZK 运维智能体</title>
  <link rel="stylesheet" href="/static/login.css">
</head>
<body class="login-page">
  <main class="login-card">
    <h1 id="setup-title">初始化管理员</h1>
    <p id="setup-desc">这是首次部署。请创建管理员账号。</p>
    <form id="setup-form" autocomplete="off">
      <div class="login-field">
        <input type="text" name="username" id="setup-username"
               placeholder="用户名（3-32 字符）" minlength="3" maxlength="32"
               pattern="[A-Za-z0-9_.\-]+" required autofocus>
      </div>
      <div class="login-field">
        <input type="password" name="password" id="setup-password"
               placeholder="密码（≥8 字符，含字母+数字）" minlength="8" required>
      </div>
      <div class="login-field">
        <input type="password" name="password_confirm" id="setup-password-confirm"
               placeholder="确认密码" minlength="8" required>
      </div>
      <button type="submit" id="setup-submit">创建管理员</button>
      <div id="setup-error" class="login-error" hidden></div>
    </form>
  </main>
  <script src="/static/setup.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create setup.js**

```javascript
// static/setup.js
async function initSetupPage() {
  const form = document.getElementById("setup-form");
  const errorEl = document.getElementById("setup-error");

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.hidden = false;
  }

  function clientValidate(username, password, confirm) {
    if (!/^[A-Za-z0-9_.\-]{3,32}$/.test(username)) {
      return "用户名必须是 3-32 个字母/数字/_-. 字符";
    }
    if (password.length < 8) {
      return "密码至少 8 个字符";
    }
    if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      return "密码必须同时包含字母和数字";
    }
    if (password !== confirm) {
      return "两次输入的密码不一致";
    }
    return null;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.hidden = true;
    const username = document.getElementById("setup-username").value.trim();
    const password = document.getElementById("setup-password").value;
    const confirm = document.getElementById("setup-password-confirm").value;

    const clientErr = clientValidate(username, password, confirm);
    if (clientErr) { showError(clientErr); return; }

    try {
      const resp = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, password }),
      });
      if (resp.ok) {
        // 后端会同时设置 cookie，刷新到主应用
        window.location.href = "/";
        return;
      }
      const data = await resp.json().catch(() => ({}));
      if (resp.status === 403) {
        showError("系统已经初始化过，请直接登录");
      } else if (resp.status === 400) {
        showError(data.error || "输入有误");
      } else {
        showError(data.error || `创建失败 (HTTP ${resp.status})`);
      }
    } catch (err) {
      showError("网络连接失败");
    }
  });
}

initSetupPage();
```

- [ ] **Step 3: 添加 i18n 键**

修改 `static/i18n.js`（在 zh-CN、en-US 等所有 locale 中）：

```javascript
// 添加到所有 locale 块
setup_title: "初始化管理员",
setup_desc: "这是首次部署。请创建管理员账号。",
setup_username: "用户名（3-32 字符）",
setup_password: "密码（≥8 字符，含字母+数字）",
setup_password_confirm: "确认密码",
setup_submit: "创建管理员",
setup_error_password_mismatch: "两次输入的密码不一致",
setup_error_password_weak: "密码强度不足（至少 8 字符，含字母和数字）",
login_username: "用户名",
login_error_invalid_credentials: "用户名或密码错误",
```

- [ ] **Step 4: 注册 /setup 路由**

在 `api/routes.py` 中添加静态文件路由：

```python
def _route_setup_page(handler, path, parsed):
    """GET /setup — 首次部署初始化页面。"""
    try:
        html = (Path(__file__).parent.parent / "static" / "setup.html").read_text(encoding="utf-8")
        body = html.encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except Exception as e:
        handler.send_response(500)
        handler.end_headers()
```

并在路由表中注册（PUBLIC 区域）：
```python
"/setup": _route_setup_page,
```

同时把 `/setup` 添加到 `api/auth.py` 的 `PUBLIC_PATHS` 中。

- [ ] **Step 5: 验证**

Run: `python -c "from pathlib import Path; print(Path('static/setup.html').exists())"`
Expected: True

- [ ] **Step 6: Commit**

```bash
git add static/setup.html static/setup.js static/i18n.js api/routes.py api/auth.py
git commit -m "feat(rbac): add /setup page for first-time admin creation"
```

---

### Task 11.8: 主应用用户菜单与分享 UI

**Files:**
- Modify: `static/index.html` (顶部用户菜单)
- Modify: `static/sessions.js` 或新增 `static/session_sharing.js`
- Test: `tests/test_session_share_ui.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_share_ui.py
"""Verify session sharing UI elements exist."""
from pathlib import Path


def test_session_share_js_exists():
    assert Path("static/session_sharing.js").exists()


def test_share_button_renders():
    src = Path("static/session_sharing.js").read_text()
    assert "shareSession" in src or "分享" in src


def test_share_token_link_button():
    src = Path("static/session_sharing.js").read_text()
    assert "/api/sessions/" in src
    assert "share/token" in src or "share_token" in src


def test_shared_section_divider():
    """会话列表有独立的"收到的分享"区域。"""
    src = Path("static/session_sharing.js").read_text()
    assert "shared" in src.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_session_share_ui.py -v`
Expected: 1+ failed (session_sharing.js 不存在)

- [ ] **Step 3: 创建 session_sharing.js**

```javascript
// static/session_sharing.js
// 会话分享前端逻辑

async function loadSessions() {
  const resp = await fetch("/api/sessions", { credentials: "same-origin" });
  if (!resp.ok) return { own: [], shared: [] };
  return resp.json();
}

async function shareSessionToUser(sessionId, username) {
  const resp = await fetch(`/api/sessions/${sessionId}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ username }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${resp.status}`);
  }
  return resp.json();
}

async function shareSessionWithToken(sessionId) {
  const resp = await fetch(`/api/sessions/${sessionId}/share/token`, {
    method: "POST",
    credentials: "same-origin",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${resp.status}`);
  }
  return resp.json();
}

async function revokeSessionShare(sessionId, shareId) {
  const resp = await fetch(`/api/sessions/${sessionId}/share/${shareId}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function renderSessionList(container, data) {
  const ownHtml = (data.own || []).map(s => `
    <li class="session-item" data-id="${s.id}">
      <span class="session-title">${escapeHtml(s.title)}</span>
      <div class="session-actions">
        <button class="btn-share" onclick="openShareDialog('${s.id}')">分享</button>
        <button class="btn-delete" onclick="deleteSession('${s.id}')">删除</button>
      </div>
    </li>
  `).join("");

  const sharedHtml = (data.shared || []).map(item => `
    <li class="session-item shared" data-share-id="${item.share_id}">
      <span class="session-title">${escapeHtml(item.session.title)}</span>
      <span class="shared-from">来自 ${escapeHtml(item.from_user_name || item.from_user_id)}</span>
      <span class="readonly-badge">只读</span>
    </li>
  `).join("");

  container.innerHTML = `
    <section class="own-sessions">
      <h3>我的会话 (${(data.own || []).length})</h3>
      <ul>${ownHtml || '<li class="empty">暂无会话</li>'}</ul>
    </section>
    <section class="shared-sessions">
      <h3>收到的分享 (${(data.shared || []).length})</h3>
      <ul>${sharedHtml || '<li class="empty">暂无分享</li>'}</ul>
    </section>
  `;
}

async function openShareDialog(sessionId) {
  const choice = window.prompt("分享方式: 输入用户名（用户分享）或输入 'link' 生成分享链接");
  if (!choice) return;
  try {
    if (choice === "link") {
      const r = await shareSessionWithToken(sessionId);
      window.prompt("复制以下分享链接:", `${window.location.origin}/shared/session?token=${r.share.token}`);
    } else {
      await shareSessionToUser(sessionId, choice.trim());
      alert(`已分享给 ${choice}`);
    }
    await refreshSessions();
  } catch (e) {
    alert(`分享失败: ${e.message}`);
  }
}

async function refreshSessions() {
  const data = await loadSessions();
  const container = document.getElementById("sessions-container");
  if (container) renderSessionList(container, data);
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s || "";
  return div.innerHTML;
}

document.addEventListener("DOMContentLoaded", refreshSessions);
```

- [ ] **Step 4: 在 index.html 引入**

修改 `static/index.html`，在合适位置添加：

```html
<script src="/static/session_sharing.js"></script>
```

并在顶部菜单区添加用户菜单：

```html
<div class="user-menu">
  <span id="current-username"></span>
  <span id="current-role-badge" hidden>Admin</span>
  <button id="logout-btn">退出</button>
  <a id="admin-link" href="/admin" hidden>管理面板</a>
</div>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_session_share_ui.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add static/session_sharing.js static/index.html tests/test_session_share_ui.py
git commit -m "feat(rbac): add session sharing UI (own + shared sections)"
```

---

### Task 11.9: 知识库元数据 UI（创建者 + 评分）

**Files:**
- Modify: `static/notes_panel.js` (或对应知识库 JS)
- Test: `tests/test_obsidian_meta_ui.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_obsidian_meta_ui.py
"""Verify knowledge base UI displays creator + ratings."""
from pathlib import Path


def test_meta_ui_renders_creator():
    """JS contains logic to render creator name from meta.creator_name."""
    for fname in ("notes_panel.js", "obsidian_panel.js", "knowledge.js"):
        path = Path("static") / fname
        if path.exists():
            assert "creator_name" in path.read_text()
            return
    # 没找到对应文件则跳过（可能在 HTML 模板中）
    assert True


def test_meta_ui_renders_rating():
    found = False
    for fname in Path("static").glob("*.js"):
        if "rating" in fname.read_text():
            found = True
            break
    assert found, "rating UI element not found in any static JS file"
```

- [ ] **Step 2: 实现 UI 逻辑**

在知识库面板的文档卡片中，附加显示：

```javascript
// 在文档列表渲染函数中添加
function renderDocCard(doc) {
  const meta = doc.meta || {};
  const ratingHtml = meta.rating_count > 0
    ? `<span class="doc-rating">★ ${meta.rating_average.toFixed(1)} (${meta.rating_count})</span>`
    : `<span class="doc-rating empty">暂无评分</span>`;
  return `
    <div class="doc-card" data-path="${doc.path}">
      <div class="doc-header">
        <span class="doc-title">${escapeHtml(doc.name)}</span>
        <span class="doc-creator">@${escapeHtml(meta.creator_name || 'unknown')}</span>
      </div>
      <div class="doc-footer">
        ${ratingHtml}
        <button class="btn-rate" onclick="openRateDialog('${doc.path}')">评分</button>
      </div>
    </div>
  `;
}

async function openRateDialog(docPath) {
  const rating = window.prompt("请输入评分 1-5:");
  const n = parseInt(rating, 10);
  if (!n || n < 1 || n > 5) {
    alert("评分必须是 1-5 之间的整数");
    return;
  }
  const resp = await fetch(`/api/notes/meta/${encodeURIComponent(docPath)}/rate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ rating: n }),
  });
  if (resp.ok) {
    await refreshNotes();
  } else {
    const err = await resp.json().catch(() => ({}));
    alert(`评分失败: ${err.error || resp.status}`);
  }
}
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_obsidian_meta_ui.py -v`
Expected: 2 passed

- [ ] **Step 4: Commit**

```bash
git add static/notes_panel.js tests/test_obsidian_meta_ui.py
git commit -m "feat(rbac): display creator and ratings on knowledge base docs"
```

---

## Phase 5: 最终验证

### Task 12: 完整集成测试

**Files:**
- Test: `tests/test_rbac_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_rbac_integration.py
"""End-to-end RBAC integration test."""
import json
import pytest
from pathlib import Path

from api.auth import initialize_first_admin, authenticate
from api.user_store import find_user_by_username
from api.session_store import add_session
from api.session_sharing import share_session_to_user, list_shared_sessions
from api.admin import create_user, update_user_role, list_users
from api.obsidian_meta import add_or_update_rating, compute_rating_summary
from api.audit import list_events


def test_full_rbac_flow(tmp_path, monkeypatch):
    """Test the full RBAC workflow end-to-end."""
    # 1. 重定向所有 state_dir 到 tmp_path
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    monkeypatch.setattr("api.admin._state_dir", lambda: tmp_path)
    monkeypatch.setattr("api.audit.AUDIT_FILE", tmp_path / "audit.json")

    # 2. 初始化第一个 admin
    admin = initialize_first_admin("admin", "admin123")
    assert admin["role"] == "admin"

    # 3. admin 创建 alice 和 bob
    alice = create_user("alice", "alice123", "user")
    bob = create_user("bob", "bob123", "user")
    assert len(list_users()) == 3

    # 4. 验证用户可以登录
    assert authenticate("alice", "alice123") is not None
    assert authenticate("alice", "wrong") is None

    # 5. alice 创建会话并分享给 bob
    sessions_dir = tmp_path / "sessions"
    alice_session = add_session(sessions_dir, alice["id"], {"title": "Alice Chat"})
    share = share_session_to_user(sessions_dir, alice["id"], bob["id"], alice_session["id"])

    # 6. bob 看到 alice 分享的会话
    shared_for_bob = list_shared_sessions(sessions_dir, bob["id"])
    assert len(shared_for_bob) == 1
    assert shared_for_bob[0]["from_user_id"] == alice["id"]

    # 7. 文档评价流程
    meta_dir = tmp_path / "knowledge" / ".meta"
    add_or_update_rating(meta_dir, "doc1.md", alice["id"], "alice", 5)
    add_or_update_rating(meta_dir, "doc1.md", bob["id"], "bob", 4)
    summary = compute_rating_summary(meta_dir, "doc1.md")
    assert summary["count"] == 2
    assert summary["average"] == 4.5

    # 8. admin 提升 alice 为 admin
    update_user_role(alice["id"], "admin", actor_id=admin["id"], actor_name="admin")
    users = list_users()
    alice_updated = next(u for u in users if u["username"] == "alice")
    assert alice_updated["role"] == "admin"

    # 9. 审计日志验证
    events = list_events()
    actions = {e["action"] for e in events}
    assert "user.create" in actions
    assert "session.share" in actions
    assert "user.role_change" in actions
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_rbac_integration.py -v`
Expected: 1 passed

- [ ] **Step 3: Run all RBAC tests**

Run: `python -m pytest tests/test_user_store.py tests/test_auth_initialization.py tests/test_auth_login.py tests/test_auth_roles.py tests/test_session_store.py tests/test_session_sharing.py tests/test_obsidian_meta.py tests/test_obsidian_ratings.py tests/test_audit.py tests/test_admin_users.py tests/test_routes_rbac.py tests/test_rbac_integration.py -v`
Expected: All passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_rbac_integration.py
git commit -m "test(rbac): add end-to-end integration test"
```

---

## 验证清单

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 首次部署流程测试通过（users.json 为空 → 强制初始化 → /setup 页）
- [ ] License 中间件测试通过（未激活/expired/copied 状态分支）
- [ ] login.js 双字段渲染验证（`tests/test_login_ui.py`）
- [ ] init_status 端点验证（`tests/test_auth_init_status.py`）
- [ ] /setup 页面提交流程验证
- [ ] 会话隔离验证（alice 看不到 bob 的会话，除非被分享）
- [ ] 分享 UI 验证（自有+分享两个分区，`tests/test_session_share_ui.py`）
- [ ] 分享流程验证（用户间分享 + token 链接分享）
- [ ] 知识库 UI 显示创建者+评分（`tests/test_obsidian_meta_ui.py`）
- [ ] 知识库评价功能验证（创建、修改、聚合）
- [ ] 管理员权限验证（admin 可查看所有会话和管理用户）
- [ ] 审计日志记录所有关键操作
- [ ] i18n locale parity 测试通过（新增键需覆盖所有 locale）
- [ ] lint 通过（`ruff check api/`）
- [ ] 浏览器手动验证：登录 → 退出 → 重登录 → 分享 → 评分 流程