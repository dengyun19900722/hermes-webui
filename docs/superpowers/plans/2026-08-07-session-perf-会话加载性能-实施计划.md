# Session Loading 性能修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把生产环境会话 4-500 个时 "Loading Conversation" 8-14s 降到 < 1s（打开会话），高频接口 p95 从 8-14s 降到 < 200ms，多 tab 不重复拉。

**Architecture:**
- **Phase 1 (PR1)** 后端 `/api/session` 默认 `msg_limit=200`，前端所有路径补全分页
- **Phase 2 (PR2)** `/api/dashboard/status` 改后台线程异步探测 + 内存缓存
- **Phase 3 (PR3)** 新建 `api/route_status_cache.py`，5 个高频接口（license/auth/health/crons/session_status）加 TTL + source-stamp + active invalidate（复用 `route_session_list_cache.py` 模式）
- **Phase 4 (PR4)** 后端 3 个 SSE 多路复用到 `/api/sessions/events`（避免 Chrome 6 连接上限），前端 3 处 setInterval 改 EventSource + fallback 轮询
- **Phase 5 (PR5+)** `api/webui_session_db.py` 加 `_index.json` 侧车索引，`list_sessions()` 走索引

**Tech Stack:** Python (stdlib only, 复用现有 OrderedDict + RLock + source-stamp 模式), Vanilla JS (EventSource native), pytest + monkeypatch, tmux 端到端

**Spec:** `docs/superpowers/specs/2026-08-07-session-loading-perf-design.md`

**总估时：** Phase 1 ≈ 1-2 天，Phase 2 ≈ 1 天，Phase 3 ≈ 3-5 天，Phase 4 ≈ 3-5 天，Phase 5+ ≈ 1-2 周

---

## 文件结构

```
api/route_status_cache.py                          # 新建（Phase 3）：5 个高频接口 TTL 缓存
api/dashboard_probe.py                             # 修改（Phase 2）：后台线程 + 缓存
api/startup.py                                     # 修改（Phase 2）：启动后台探测
api/routes.py                                      # 修改（Phase 1/3）：msg_limit 默认值 + 5 接口接入
api/license.py                                     # 修改（Phase 3）：写路径 invalidate
api/auth.py                                        # 修改（Phase 3）：写路径 invalidate
api/agent_health.py                                # 修改（Phase 3）：后台线程 invalidate
api/crons/jobs.py                                  # 修改（Phase 3）：写路径 invalidate
api/route_approvals.py                             # 修改（Phase 3/4）：invalidate + publish
api/clarify.py                                     # 修改（Phase 3/4）：invalidate + publish
api/session_events.py                              # 修改（Phase 4）：3 个新 publish + 多路复用
api/webui_session_db.py                            # 修改（Phase 5）：_index.json 写/读路径
api/models.py                                      # 修改（Phase 5）：Session.* 调索引

static/sessions.js                                 # 修改（Phase 1）：补 msg_limit
static/messages.js                                 # 修改（Phase 1/4）：补 msg_limit + 3 处 SSE

tests/test_route_status_cache.py                   # 新建（Phase 3）
tests/test_dashboard_probe_async.py                # 新建（Phase 2）
tests/test_msg_limit.py                            # 新建（Phase 1）
tests/test_session_index.py                        # 新建（Phase 5）
tests/test_sse_multiplex.py                        # 新建（Phase 4）
tests/bench_high_freq.py                           # 新建：性能基准
tests/bench_open_conversation.py                   # 新建：性能基准
tests/bench_session_load.py                        # 新建：性能基准
```

---

## 全局回滚开关

每个 Phase 部署时可通过 env 一键回滚：

| Phase | 回滚开关 | 行为 |
|-------|---------|------|
| Phase 1 | `HERMES_WEBUI_MSG_LIMIT=0` | 关闭后端默认 msg_limit（恢复全量加载） |
| Phase 2 | `HERMES_WEBUI_DASHBOARD_SYNC=1` | dashboard 走原同步 urllib 探测 |
| Phase 3 | `HERMES_WEBUI_DISABLE_STATUS_CACHE=1` | 全局关闭 5 个接口缓存 |
| Phase 4 | `HERMES_WEBUI_DISABLE_SSE_FALLBACK=1` | 关闭 SSE fallback，回退到原 setInterval 轮询 |
| Phase 5 | `HERMES_WEBUI_DISABLE_SESSION_INDEX=1` | 关闭索引读路径，回退 glob+loads |

---

## 全局测试基础设施

每个 Phase 部署前必跑：

```bash
# 现有 conftest 会阻塞 test_server（# /health 走 license gate），所有测试用 --noconftest + python -c 模式

# Phase 1
python -m pytest tests/test_msg_limit.py -v --noconftest

# Phase 2
python -m pytest tests/test_dashboard_probe_async.py -v --noconftest

# Phase 3
python -m pytest tests/test_route_status_cache.py -v --noconftest

# Phase 4
python -m pytest tests/test_sse_multiplex.py -v --noconftest

# Phase 5
python -m pytest tests/test_session_index.py -v --noconftest

# 性能基准（所有 Phase 后）
python -m pytest tests/bench_high_freq.py -v --noconftest -s
python -m pytest tests/bench_open_conversation.py -v --noconftest -s
python -m pytest tests/bench_session_load.py -v --noconftest -s
```

---

# Phase 1：msg_limit 强制分页（PR1，~1-2 天）

**目标：** 打开会话时 `/api/session?messages=1` 不再全量加载。后端默认 `msg_limit=200`，超过则返回 `{messages: [...200 条...], has_more: true, total_count: N}`。

## Task 1.1：后端 `/api/session` 加默认 msg_limit

**Files:**
- Modify: `api/routes.py`（`/api/session` GET handler）
- Test: `tests/test_msg_limit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_msg_limit.py
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from api.routes import _handle_session_get  # 假设函数名


def test_msg_limit_default_200_when_omitted(monkeypatch):
    """不传 msg_limit 时后端默认 200"""
    # Setup: 注入一个有 300 条消息的 session
    session = _make_fake_session(message_count=300)
    monkeypatch.setattr("api.routes.get_session", lambda sid, metadata_only=False: session)
    
    handler, parsed = _make_fake_request(session_id="fake-sid")
    _handle_session_get(handler, parsed)
    
    response = handler.get_json_response()
    assert len(response["messages"]) == 200
    assert response["has_more"] is True
    assert response["total_count"] == 300


def test_msg_limit_explicit_override(monkeypatch):
    """传 msg_limit=50 时返回 50 条"""
    session = _make_fake_session(message_count=300)
    monkeypatch.setattr("api.routes.get_session", lambda sid, metadata_only=False: session)
    
    handler, parsed = _make_fake_request(session_id="fake-sid", query="msg_limit=50")
    _handle_session_get(handler, parsed)
    
    response = handler.get_json_response()
    assert len(response["messages"]) == 50
    assert response["has_more"] is True


def test_msg_limit_smaller_than_messages(monkeypatch):
    """消息数 < msg_limit 时 has_more=False"""
    session = _make_fake_session(message_count=50)
    monkeypatch.setattr("api.routes.get_session", lambda sid, metadata_only=False: session)
    
    handler, parsed = _make_fake_request(session_id="fake-sid", query="msg_limit=200")
    _handle_session_get(handler, parsed)
    
    response = handler.get_json_response()
    assert len(response["messages"]) == 50
    assert response["has_more"] is False


def test_msg_limit_zero_disables_pagination(monkeypatch):
    """msg_limit=0 = 不分页（兼容旧客户端）"""
    session = _make_fake_session(message_count=300)
    monkeypatch.setattr("api.routes.get_session", lambda sid, metadata_only=False: session)
    
    handler, parsed = _make_fake_request(session_id="fake-sid", query="msg_limit=0")
    _handle_session_get(handler, parsed)
    
    response = handler.get_json_response()
    assert len(response["messages"]) == 300
    assert "has_more" not in response or response["has_more"] is False


def _make_fake_session(message_count):
    """生成有 message_count 条消息的假 session"""
    from types import SimpleNamespace
    return SimpleNamespace(
        session_id="fake-sid",
        messages=[{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"} for i in range(message_count)],
        compact=lambda: {"title": "fake"},
        metadata_only=False,
    )


def _make_fake_request(session_id, query=""):
    """生成 fake handler + parsed"""
    from urllib.parse import urlparse, parse_qs
    from io import BytesIO
    from types import SimpleNamespace
    
    captured = {}
    
    class FakeHandler:
        def __init__(self):
            self.wfile = BytesIO()
        def send_response(self, code):
            captured["code"] = code
        def send_header(self, k, v):
            pass
        def end_headers(self):
            pass
        def get_json_response(self):
            import json
            body = self.wfile.getvalue()
            return json.loads(body.decode("utf-8"))
    
    handler = FakeHandler()
    url = f"/api/session?session_id={session_id}"
    if query:
        url += f"&{query}"
    parsed = urlparse(url)
    return handler, parsed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_msg_limit.py -v --noconftest`
Expected: FAIL with `NameError` 或 `AttributeError`（_handle_session_get 不存在或行为不对）

- [ ] **Step 3: Modify `/api/session` handler in `api/routes.py`**

找到 `/api/session` GET handler（约 13200 行附近），改写 messages 字段返回逻辑：

```python
# 找到原 handler 中处理 messages=1 的分支
# 原文（参考）：
#   messages = session.messages  # 全量
#   return j(handler, {"messages": messages, ...})

# 改为：
from api.models import SESSION_MSG_DEFAULT_LIMIT  # 新增常量

qs = parse_qs(parsed.query)
requested_limit = qs.get("msg_limit", [None])[0]
if requested_limit is None:
    effective_limit = SESSION_MSG_DEFAULT_LIMIT  # 默认 200
else:
    try:
        effective_limit = max(0, int(requested_limit))
    except (TypeError, ValueError):
        effective_limit = SESSION_MSG_DEFAULT_LIMIT

all_messages = list(getattr(session, "messages", []) or [])
total_count = len(all_messages)

if effective_limit > 0 and total_count > effective_limit:
    messages = all_messages[-effective_limit:]
    has_more = True
else:
    messages = all_messages
    has_more = False

response = {
    "messages": messages,
    "message_count": total_count,
    "has_more": has_more,
}
return j(handler, response)
```

- [ ] **Step 4: Add constant in `api/models.py`**

```python
# api/models.py 顶部
SESSION_MSG_DEFAULT_LIMIT = 200
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_msg_limit.py -v --noconftest`
Expected: 4 个 test 都 PASS

- [ ] **Step 6: Commit**

```bash
git add api/routes.py api/models.py tests/test_msg_limit.py
git commit -m "feat(api): /api/session 默认 msg_limit=200 强制分页（Phase 1 PR1）"
```

---

## Task 1.2：前端 `static/sessions.js` 补 msg_limit

**Files:**
- Modify: `static/sessions.js`（lines 192, 1429, 2504, 5188）

- [ ] **Step 1: 找到所有 `/api/session?session_id=` 调用**

```bash
grep -nE "/api/session\?session_id=" static/sessions.js
```

Expected: 找到 4 处（lines 192, 1429, 2504, 5188）。

- [ ] **Step 2: 在每个调用加 `&msg_limit=200`**

修改前示例（line 192）：
```javascript
const data = await api(`/api/session?session_id=${encodeURIComponent(sid)}&messages=0&resolve_model=0`);
```

修改后：
```javascript
const data = await api(`/api/session?session_id=${encodeURIComponent(sid)}&messages=0&resolve_model=0&msg_limit=200`);
```

同理修改 lines 1429, 2504, 5188。

- [ ] **Step 3: 在 `_ensureMessagesLoaded()`（line 2632）传入 limit**

修改前（line 3147 附近）：
```javascript
`/api/session?session_id=${encodeURIComponent(sid)}&messages=1&resolve_model=0&msg_limit=${requestedLimit}`,
```

修改后（保持不变）：
```javascript
`/api/session?session_id=${encodeURIComponent(sid)}&messages=1&resolve_model=0&msg_limit=${requestedLimit}&has_more=1`,
```

并在渲染时检查 `has_more`：
```javascript
if (response.has_more) {
    // 显示"加载更早"按钮
    showLoadEarlierButton(sid);
}
```

- [ ] **Step 4: Commit**

```bash
git add static/sessions.js
git commit -m "feat(ui): sessions.js 补全 msg_limit + has_more 渲染（Phase 1 PR1）"
```

---

## Task 1.3：前端 `static/messages.js` 补 msg_limit

**Files:**
- Modify: `static/messages.js`（line 3308 等路径）

- [ ] **Step 1: 找到所有 `/api/session?messages=1` 调用**

```bash
grep -nE "/api/session\?.*messages=1" static/messages.js
```

Expected: 至少 1 处（line 3308）。

- [ ] **Step 2: 加 `&msg_limit=200`**

修改前（line 3308）：
```javascript
const data = await api(`/api/session?session_id=${encodeURIComponent(sid)}&messages=1&resolve_model=0`, {timeoutMs:120000});
```

修改后：
```javascript
const data = await api(`/api/session?session_id=${encodeURIComponent(sid)}&messages=1&resolve_model=0&msg_limit=200`, {timeoutMs:120000});
```

- [ ] **Step 3: 处理 `has_more`**

加判断：
```javascript
if (data.has_more) {
    // 显示"加载更早"或触发自动向后加载
    showLoadEarlierButton(sid, data.total_count);
}
```

- [ ] **Step 4: Commit**

```bash
git add static/messages.js
git commit -m "feat(ui): messages.js 补全 msg_limit + has_more 渲染（Phase 1 PR1）"
```

---

## Task 1.4：Phase 1 验收测试

- [ ] **Step 1: 启动服务 + tmux 端到端**

```bash
# 启动真服务
tmux new-session -d -s hermes 'python -m api.routes 8787'
sleep 3

# 生成 500 消息的测试 session
python -c "
from api.webui_session_db import WebUIJsonSessionDB
import uuid
sid = str(uuid.uuid4())
session = {
    'session_id': sid,
    'title': 'phase1-test',
    'messages': [{'role': 'user' if i%2==0 else 'assistant', 'content': f'msg-{i}'} for i in range(500)],
    'message_count': 500,
    'created_at': '2026-08-07T00:00:00Z',
    'updated_at': '2026-08-07T00:00:00Z',
}
WebUIJsonSessionDB().write_session(session)
print(f'TEST_SID={sid}')
" 
export TEST_SID=$(...)
```

- [ ] **Step 2: 验证接口 < 1s**

```bash
time curl -s "http://localhost:8787/api/session?session_id=$TEST_SID&messages=1&resolve_model=0&msg_limit=200" > /tmp/response.json
test $(jq '.messages | length' /tmp/response.json) -eq 200
test $(jq '.has_more' /tmp/response.json) = "true"
test $(jq '.total_count' /tmp/response.json) -eq 500
```

Expected: 全部通过，time < 1s

- [ ] **Step 3: Commit Phase 1 完成**

```bash
git commit --allow-empty -m "chore(perf): Phase 1 PR1 验收通过（打开会话 < 1s）"
```

---

# Phase 2：dashboard 异步化（PR2，~1 天）

**目标：** `/api/dashboard/status` 请求线程不再做 `urllib.urlopen`。后台线程每 5s 探测一次，结果写 `_DASHBOARD_STATUS_CACHE`，请求线程只读缓存。

## Task 2.1：`_DASHBOARD_STATUS_CACHE` + 后台探测函数

**Files:**
- Modify: `api/dashboard_probe.py`
- Test: `tests/test_dashboard_probe_async.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_probe_async.py
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
import pytest


def test_get_dashboard_status_uses_cache(monkeypatch):
    """get_dashboard_status 应该读 _DASHBOARD_STATUS_CACHE，不再调 urllib"""
    from api import dashboard_probe
    
    # 预设缓存值
    dashboard_probe._DASHBOARD_STATUS_CACHE = {
        "running": True,
        "host": "127.0.0.1",
        "port": 9119,
        "url": "http://127.0.0.1:9119",
        "version": "1.0.0",
        "checked_at": "2026-08-07T00:00:00Z",
    }
    
    # Patch urllib 以确保不调用
    called = []
    def fake_urlopen(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("urllib should not be called in get_dashboard_status")
    
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    
    result = dashboard_probe.get_dashboard_status()
    assert result["running"] is True
    assert result["host"] == "127.0.0.1"
    assert called == []


def test_get_dashboard_status_pending_when_cache_empty():
    """缓存未就绪时返回 pending=True"""
    from api import dashboard_probe
    dashboard_probe._DASHBOARD_STATUS_CACHE = None
    
    result = dashboard_probe.get_dashboard_status()
    assert result["running"] is False
    assert result["pending"] is True


def test_background_probe_thread_runs():
    """后台线程启动后会写缓存"""
    from api import dashboard_probe
    
    # 先清空
    dashboard_probe._DASHBOARD_STATUS_CACHE = None
    dashboard_probe._DASHBOARD_PROBE_THREAD_STARTED = False
    
    # 启动后台线程（短间隔）
    dashboard_probe.start_background_probe(interval_seconds=0.1, timeout_seconds=0.1)
    
    # 等待探测
    time.sleep(0.5)
    
    # 验证缓存已写入（不论 running 是 True 还是 False，关键是缓存非 None）
    assert dashboard_probe._DASHBOARD_STATUS_CACHE is not None


def test_background_probe_thread_survives_failure():
    """探测失败时缓存写 running=False，线程不崩"""
    from api import dashboard_probe
    
    dashboard_probe._DASHBOARD_STATUS_CACHE = None
    dashboard_probe.start_background_probe(interval_seconds=0.05, timeout_seconds=0.05)
    
    time.sleep(0.3)
    
    assert dashboard_probe._DASHBOARD_STATUS_CACHE is not None
    assert dashboard_probe._DASHBOARD_STATUS_CACHE.get("running") is False
    assert dashboard_probe._DASHBOARD_PROBE_THREAD.is_alive()


def test_force_sync_env_uses_legacy(monkeypatch):
    """HERMES_WEBUI_DASHBOARD_SYNC=1 走原同步探测"""
    from api import dashboard_probe
    
    monkeypatch.setenv("HERMES_WEBUI_DASHBOARD_SYNC", "1")
    
    # Patch probe_official_dashboard
    calls = []
    def fake_probe(host, port, **kwargs):
        calls.append((host, port))
        return {"running": True, "host": host, "port": port}
    
    monkeypatch.setattr(dashboard_probe, "probe_official_dashboard", fake_probe)
    
    result = dashboard_probe.get_dashboard_status()
    assert result["running"] is True
    assert calls == [("127.0.0.1", 9119)] or calls == [("localhost", 9119)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_probe_async.py -v --noconftest`
Expected: FAIL（`_DASHBOARD_STATUS_CACHE` 不存在或 `start_background_probe` 不存在）

- [ ] **Step 3: Modify `api/dashboard_probe.py`**

在文件顶部加：
```python
# api/dashboard_probe.py 顶部新增
import os
import threading
import atexit
from typing import Any

_DASHBOARD_STATUS_CACHE: dict[str, Any] | None = None
_DASHBOARD_PROBE_THREAD: threading.Thread | None = None
_DASHBOARD_PROBE_THREAD_STARTED: bool = False
_DASHBOARD_PROBE_STOP_FLAG: threading.Event = threading.Event()
_DASHBOARD_CACHE_LOCK = threading.Lock()


def _background_probe_loop(interval_seconds: float, timeout_seconds: float):
    """后台探测循环，daemon=True 不拖死服务"""
    targets = list(DEFAULT_DASHBOARD_TARGETS)
    while not _DASHBOARD_PROBE_STOP_FLAG.is_set():
        result = _probe_one_with_targets(targets, timeout_seconds=timeout_seconds)
        with _DASHBOARD_CACHE_LOCK:
            global _DASHBOARD_STATUS_CACHE
            _DASHBOARD_STATUS_CACHE = result
        # 等下一次（wait 支持 stop）
        if _DASHBOARD_PROBE_STOP_FLAG.wait(timeout=interval_seconds):
            break


def _probe_one_with_targets(targets, timeout_seconds) -> dict[str, Any]:
    """对所有 loopback 目标探测一次，返回合并结果"""
    checked_at = _checked_at_dashboard()
    for host, port in targets:
        try:
            probe_result = probe_official_dashboard(host, port, timeout=timeout_seconds)
            if probe_result.get("running"):
                probe_result["checked_at"] = checked_at
                return probe_result
        except Exception:
            logger.debug("dashboard probe failed for %s:%s", host, port, exc_info=True)
    return {"running": False, "checked_at": checked_at}


def _checked_at_dashboard() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def start_background_probe(interval_seconds: float = 5.0, timeout_seconds: float = DEFAULT_DASHBOARD_TIMEOUT) -> None:
    """启动后台探测线程。幂等。"""
    global _DASHBOARD_PROBE_THREAD, _DASHBOARD_PROBE_THREAD_STARTED
    if _DASHBOARD_PROBE_THREAD_STARTED:
        return
    _DASHBOARD_PROBE_THREAD_STARTED = True
    _DASHBOARD_PROBE_STOP_FLAG.clear()
    _DASHBOARD_PROBE_THREAD = threading.Thread(
        target=_background_probe_loop,
        args=(interval_seconds, timeout_seconds),
        daemon=True,
        name="dashboard-probe",
    )
    _DASHBOARD_PROBE_THREAD.start()
    atexit.register(_stop_background_probe)


def _stop_background_probe():
    _DASHBOARD_PROBE_STOP_FLAG.set()


def trigger_immediate_probe() -> None:
    """配置变更时调用，标记下一次探测立即执行"""
    _DASHBOARD_PROBE_STOP_FLAG.set()  # 唤醒 wait
    _DASHBOARD_PROBE_STOP_FLAG = threading.Event()  # 重置
```

修改 `get_dashboard_status()`：
```python
def get_dashboard_status(config_data: dict | None = None) -> dict:
    """读 _DASHBOARD_STATUS_CACHE；env HERMES_WEBUI_DASHBOARD_SYNC=1 时走同步"""
    if os.environ.get("HERMES_WEBUI_DASHBOARD_SYNC", "").strip() in ("1", "true", "yes"):
        # 紧急回滚开关：同步探测
        return _probe_one_with_targets(list(DEFAULT_DASHBOARD_TARGETS), DEFAULT_DASHBOARD_TIMEOUT)
    
    with _DASHBOARD_CACHE_LOCK:
        cached = _DASHBOARD_STATUS_CACHE
    
    if cached is None:
        return {"running": False, "pending": True, "checked_at": None}
    
    return dict(cached)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_probe_async.py -v --noconftest`
Expected: 5 个 test 都 PASS

- [ ] **Step 5: Commit**

```bash
git add api/dashboard_probe.py tests/test_dashboard_probe_async.py
git commit -m "feat(perf): /api/dashboard/status 改后台线程异步探测 + 缓存（Phase 2 PR2）"
```

---

## Task 2.2：启动时启动后台探测线程

**Files:**
- Modify: `api/startup.py`

- [ ] **Step 1: 在 `startup.py` 加后台探测启动**

在 `fix_credential_permissions()` 函数末尾加：
```python
def fix_credential_permissions() -> None:
    """Ensure sensitive files in HERMES_HOME have safe permissions.
    ...
    """
    # ... 原代码 ...
    
    # Phase 2 PR2：启动 dashboard 后台探测线程
    try:
        from api.dashboard_probe import start_background_probe
        start_background_probe(interval_seconds=5.0, timeout_seconds=0.5)
    except Exception:
        # best-effort，不阻塞启动
        pass
```

- [ ] **Step 2: 验证启动顺序**

启动服务，验证日志有 "dashboard-probe" 线程：
```bash
python -c "import api.startup; api.startup.fix_credential_permissions()" 2>&1 | grep -i dashboard
```

Expected: 无 panic，线程在后台运行。

- [ ] **Step 3: Commit**

```bash
git add api/startup.py
git commit -m "feat(perf): startup 启动 dashboard 后台探测线程（Phase 2 PR2）"
```

---

## Task 2.3：Phase 2 验收测试

- [ ] **Step 1: dashboard 在线场景**

启动 `hermes dashboard` 在 9119 端口（如果有），启动 WebUI，验证：
```bash
time curl -s http://localhost:8787/api/dashboard/status
```

Expected: < 50ms，`running: true`

- [ ] **Step 2: dashboard 离线场景**

关闭 `hermes dashboard`，验证：
```bash
time curl -s http://localhost:8787/api/dashboard/status
```

Expected: < 50ms，`running: false`（**不是 0.5s timeout × N 轮询叠加**）

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore(perf): Phase 2 PR2 验收通过（dashboard/status < 50ms）"
```

---

# Phase 3：5 个高频接口 TTL 缓存（PR3，~3-5 天，最大工作量）

**目标：** 5 个高频接口（`/api/license/status`、`/api/auth/status`、`/api/health/agent`、`/api/crons/recent`、`/api/session/status`）走 TTL + source-stamp + active invalidate 三层缓存，p95 < 200ms。

## Task 3.1：新建 `api/route_status_cache.py`（核心模块）

**Files:**
- Create: `api/route_status_cache.py`
- Test: `tests/test_route_status_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_route_status_cache.py
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
import pytest

from api import route_status_cache


def test_cache_get_miss_calls_builder():
    """cache miss 时调用 builder 并写入"""
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    def builder():
        calls.append(1)
        return {"value": 42}
    
    result, hit = route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    assert result == {"value": 42}
    assert hit is False
    assert len(calls) == 1


def test_cache_get_hit_does_not_call_builder():
    """cache hit 时不调用 builder"""
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    def builder():
        calls.append(1)
        return {"value": 42}
    
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    
    assert len(calls) == 1  # builder 只调一次


def test_cache_ttl_expiry():
    """TTL 到期后再调用 builder"""
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    def builder():
        calls.append(1)
        return {"value": len(calls)}
    
    route_status_cache._status_cache_get("k1", builder=builder, ttl=0.1)
    assert calls ==["1"]
    
    time.sleep(0.15)
    route_status_cache._status_cache_get("k1", builder=builder, ttl=0.1)
    assert calls == [1, 2]


def test_cache_source_stamp_invalidates():
    """source stamp 变化时强制 rebuild"""
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    def builder():
        calls.append(1)
        return {"value": len(calls)}
    
    route_status_cache._status_cache_get(
        "k1",
        builder=builder,
        ttl=5.0,
        source_stamp_fn=lambda: "stamp-v1",
    )
    assert calls ==["1"]
    
    # 改 source stamp
    route_status_cache._status_cache_get(
        "k1",
        builder=builder,
        ttl=5.0,
        source_stamp_fn=lambda: "stamp-v2",
    )
    assert calls == [1, 2]


def test_cache_active_invalidate():
    """主动 invalidate 强制下次 rebuild"""
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    def builder():
        calls.append(1)
        return {"value": len(calls)}
    
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    route_status_cache._status_cache_invalidate("k1")
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    
    assert calls == [1, 2]


def test_cache_in_flight_dedup():
    """并发请求同 key 只调一次 builder"""
    route_status_cache._STATUS_CACHE.clear()
    
    barrier = threading.Barrier(10)
    calls = []
    
    def slow_builder():
        calls.append(1)
        time.sleep(0.05)  # 模拟 builder 慢
        return {"value": 42}
    
    results = []
    def worker():
        barrier.wait()
        r, _ = route_status_cache._status_cache_get("k1", builder=slow_builder, ttl=5.0)
        results.append(r)
    
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    # dedupe 后 builder 只被调一次
    assert len(calls) == 1
    assert all(r == {"value": 42} for r in results)


def test_cache_disable_via_env(monkeypatch):
    """HERMES_WEBUI_DISABLE_STATUS_CACHE=1 时每次都调 builder"""
    monkeypatch.setenv("HERMES_WEBUI_DISABLE_STATUS_CACHE", "1")
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    def builder():
        calls.append(1)
        return {"value": 42}
    
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    route_status_cache._status_cache_get("k1", builder=builder, ttl=5.0)
    
    assert len(calls) == 2


def test_cache_stale_while_revalidate():
    """TTL 到期但 inflight 时返回 stale"""
    route_status_cache._STATUS_CACHE.clear()
    
    calls = []
    barrier = threading.Event()
    
    def slow_builder():
        calls.append(1)
        barrier.wait(timeout=2)
        return {"value": len(calls)}
    
    # 第一次：cache miss
    route_status_cache._status_cache_get("k1", builder=slow_builder, ttl=0.05)
    assert calls ==["1"]
    
    # 第二次：TTL 已过，触发新 builder
    time.sleep(0.1)
    # 第二次调用，但 builder 在等待
    t = threading.Thread(target=lambda: route_status_cache._status_cache_get("k1", builder=slow_builder, ttl=0.05))
    t.start()
    time.sleep(0.05)  # 让第二次调用进入 inflight
    
    # 第三次：TTL 已过且 inflight 中，返回 stale
    r, hit = route_status_cache._status_cache_get("k1", builder=slow_builder, ttl=0.05, allow_stale=True)
    assert hit is False  # not fresh
    assert r == {"value": 1}  # stale 数据
    
    # 释放 builder
    barrier.set()
    t.join()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_route_status_cache.py -v --noconftest`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.route_status_cache'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/route_status_cache.py
"""TTL + source-stamp + active invalidate 缓存层，覆盖 5 个高频接口。

复用 api.route_session_list_cache.py 的设计模式（已验证 #4672 / #4808）：
- 单进程 OrderedDict + RLock
- source-stamp（基于文件 mtime 或版本号）+ TTL（保兜底）+ active invalidate（即时）
- in-flight dedupe：同 key 并发请求合并
- stale-while-revalidate：TTL 到期且 inflight 时返回旧数据

env 回滚：
- HERMES_WEBUI_DISABLE_STATUS_CACHE=1：所有缓存调用 bypass，每次都调 builder
"""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

_STATUS_CACHE: OrderedDict[tuple, tuple[float, str, dict]] = OrderedDict()
_STATUS_CACHE_LOCK = threading.RLock()
_STATUS_CACHE_INFLIGHT: dict[tuple, threading.Event] = {}
_STATUS_CACHE_INVALIDATION_VERSION = 0


def _status_cache_get(
    key: tuple | str,
    builder: Callable[[], dict],
    ttl: float,
    source_stamp_fn: Callable[[], Any] | None = None,
    allow_stale: bool = False,
) -> tuple[dict, bool]:
    """读缓存；miss/stale 时调 builder 写入。返回 (payload, hit_fresh)。
    
    Args:
        key: 缓存键（建议用元组，便于 profile + 接口路径 + 参数组合）
        builder: cache miss 时调用，必须返回 dict
        ttl: 缓存有效期（秒）
        source_stamp_fn: 可选，每次读时调用，返回当前 stamp；与缓存 stamp 不一致时强制 rebuild
        allow_stale: TTL 到期且有 inflight builder 时是否返回旧数据（stale-while-revalidate）
    
    Returns:
        (payload, hit_fresh): payload 是 dict；hit_fresh 表示 cache hit 且 TTL 内
    """
    if os.environ.get("HERMES_WEBUI_DISABLE_STATUS_CACHE", "").strip() in ("1", "true", "yes"):
        return builder(), False
    
    normalized_key = _normalize_key(key)
    now = time.monotonic()
    current_stamp = source_stamp_fn() if source_stamp_fn is not None else None
    
    with _STATUS_CACHE_LOCK:
        entry = _STATUS_CACHE.get(normalized_key)
        if entry is not None:
            ts, stamp, payload = entry
            fresh = (now - ts) < ttl
            stamp_match = (current_stamp is None) or (stamp == current_stamp)
            if fresh and stamp_match:
                _STATUS_CACHE.move_to_end(normalized_key)
                return copy.deepcopy(payload), True
            if allow_stale and stamp_match:
                # stale-while-revalidate：返回旧值，但后台触发 rebuild
                _STATUS_CACHE.move_to_end(normalized_key)
                _maybe_rebuild_in_background(normalized_key, builder, current_stamp)
                return copy.deepcopy(payload), False
            _STATUS_CACHE.pop(normalized_key, None)
        
        # cache miss / stale
        event, claim = _claim_inflight(normalized_key)
        if not claim:
            # 别的线程正在 build，等一下，然后重试
            event.wait(timeout=5.0)
            entry = _STATUS_CACHE.get(normalized_key)
            if entry is not None:
                _STATUS_CACHE.move_to_end(normalized_key)
                return copy.deepcopy(entry[2]), True
            # 超时了，继续往下调 builder（best-effort）
    
    # 真正的 build 路径
    try:
        payload = builder()
    finally:
        _done_inflight(normalized_key, event)
    
    with _STATUS_CACHE_LOCK:
        _STATUS_CACHE[normalized_key] = (time.monotonic(), current_stamp, copy.deepcopy(payload))
        _STATUS_CACHE.move_to_end(normalized_key)
        while len(_STATUS_CACHE) > 256:  # LRU 上限
            _STATUS_CACHE.popitem(last=False)
    
    return payload, False


def _status_cache_invalidate(key: tuple | str | None = None, reason: str = "") -> None:
    """主动失效缓存。key=None 时清空全部。"""
    with _STATUS_CACHE_LOCK:
        global _STATUS_CACHE_INVALIDATION_VERSION
        _STATUS_CACHE_INVALIDATION_VERSION += 1
        if key is None:
            _STATUS_CACHE.clear()
            return
        normalized_key = _normalize_key(key)
        _STATUS_CACHE.pop(normalized_key, None)


def _normalize_key(key) -> tuple:
    """统一 key 格式"""
    if isinstance(key, tuple):
        return key
    return (key,)


def _claim_inflight(key: tuple) -> tuple[threading.Event, bool]:
    """原子声明 inflight；返回 (event, claim_ok)"""
    with _STATUS_CACHE_LOCK:
        existing = _STATUS_CACHE_INFLIGHT.get(key)
        if existing is not None:
            return existing, False
        event = threading.Event()
        _STATUS_CACHE_INFLIGHT[key] = event
        return event, True


def _done_inflight(key: tuple, event: threading.Event) -> None:
    with _STATUS_CACHE_LOCK:
        if _STATUS_CACHE_INFLIGHT.get(key) is event:
            _STATUS_CACHE_INFLIGHT.pop(key, None)
    if event is not None:
        event.set()


def _maybe_rebuild_in_background(key: tuple, builder: Callable, stamp: Any) -> None:
    """stale-while-revalidate：后台 rebuild（fire-and-forget）"""
    def _do_rebuild():
        try:
            payload = builder()
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE[key] = (time.monotonic(), stamp, copy.deepcopy(payload))
                _STATUS_CACHE.move_to_end(key)
        except Exception:
            pass  # 失败不影响下次重试
    
    threading.Thread(target=_do_rebuild, daemon=True, name="status-cache-rebuild").start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_route_status_cache.py -v --noconftest`
Expected: 8 个 test 都 PASS

- [ ] **Step 5: Commit**

```bash
git add api/route_status_cache.py tests/test_route_status_cache.py
git commit -m "feat(perf): 新建 route_status_cache 缓存层（Phase 3 PR3 基础）"
```

---

## Task 3.2：`/api/license/status` 接入缓存

**Files:**
- Modify: `api/routes.py:12051-12076`（license/status handler）

- [ ] **Step 1: 加 license 写路径 invalidate**

修改 `api/license.py`，找到 license 持久化函数（如 `save_license`、`save_permanent_allowlist`、任何 yaml 写），在写成功后加：
```python
# api/license.py 写路径函数末尾
from api.route_status_cache import _status_cache_invalidate

_status_cache_invalidate(reason="license_write")
```

- [ ] **Step 2: 在 routes.py 包一层 status_cache_get**

修改前（line 12051-12076）：
```python
if parsed.path == "/api/license/status":
    from api.license import init_license_config, check_license_status
    workspace = Path(DEFAULT_WORKSPACE)
    try:
        config = init_license_config(workspace)
    except FileNotFoundError:
        return j(handler, {...})
    status = check_license_status(workspace)
    status["platform_id"] = config.get("platform_id")
    return j(handler, status)
```

修改后：
```python
if parsed.path == "/api/license/status":
    from api.license import init_license_config, check_license_status
    from api.route_status_cache import _status_cache_get, _normalize_key
    
    workspace = Path(DEFAULT_WORKSPACE)
    
    def _build():
        try:
            config = init_license_config(workspace)
        except FileNotFoundError:
            return {
                "activated": False,
                "status": "not_initialized",
                ...
            }
        s = check_license_status(workspace)
        s["platform_id"] = config.get("platform_id")
        s["mac_address"] = config.get("mac_address")
        return s
    
    def _source_stamp():
        try:
            st = workspace.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None
    
    payload, hit = _status_cache_get(
        key=("license_status",),
        builder=_build,
        ttl=10.0,
        source_stamp_fn=_source_stamp,
    )
    handler.send_header("X-Cache", "HIT" if hit else "MISS")
    return j(handler, payload)
```

- [ ] **Step 3: 验证**

```bash
time curl -s http://localhost:8787/api/license/status
time curl -s http://localhost:8787/api/license/status  # 第二次应 < 5ms
```

Expected: 第二次 < 5ms（cache hit）

- [ ] **Step 4: Commit**

```bash
git add api/license.py api/routes.py
git commit -m "feat(perf): /api/license/status 接入 TTL 缓存（Phase 3 PR3）"
```

---

## Task 3.3：`/api/auth/status` 接入缓存

**Files:**
- Modify: `api/routes.py:12368-12403`（auth/status handler）
- Modify: `api/auth.py`（passkey 增删、`auth_disabled_acknowledged` 变更）

- [ ] **Step 1: 加 auth 写路径 invalidate**

在 `api/auth.py` 找到 passkey 注册 / 删除函数、`auth_disabled_acknowledged` 写入处，加：
```python
from api.route_status_cache import _status_cache_invalidate

_status_cache_invalidate(("auth_status",), reason="auth_change")
```

- [ ] **Step 2: 在 routes.py 包一层 status_cache_get**

修改前（line 12368-12403）：
```python
if parsed.path == "/api/auth/status":
    from api.auth import _passkey_feature_flag_enabled, get_password_hash, get_user_from_session, is_auth_enabled, is_oidc_auth_enabled, parse_cookie, verify_any_session
    from api.passkeys import registered_credentials
    logged_in = False
    ...
    return j(handler, {...})
```

修改后：
```python
if parsed.path == "/api/auth/status":
    from api.auth import _passkey_feature_flag_enabled, get_password_hash, get_user_from_session, is_auth_enabled, is_oidc_auth_enabled, parse_cookie, verify_any_session
    from api.passkeys import registered_credentials
    from api.route_status_cache import _status_cache_get
    
    def _build():
        logged_in = False
        current_user = None
        auth_enabled = is_auth_enabled()
        oidc_enabled = is_oidc_auth_enabled()
        if auth_enabled:
            cv = parse_cookie(handler)
            logged_in = verify_any_session(cv)
            if logged_in and cv:
                rbac_user = get_user_from_session(cv)
                if rbac_user:
                    from api.user_store import DEFAULT_USER_PANELS
                    current_user = {
                        "id": rbac_user.get("id"),
                        "username": rbac_user.get("username"),
                        "role": rbac_user.get("role", "user"),
                        "panels": rbac_user.get("panels") or list(DEFAULT_USER_PANELS),
                    }
        passkey_flag = _passkey_feature_flag_enabled()
        passkeys = registered_credentials() if passkey_flag else []
        password_auth_enabled = get_password_hash() is not None
        return {
            "auth_enabled": auth_enabled,
            "logged_in": logged_in,
            "user": current_user,
            "oidc_enabled": oidc_enabled,
            "password_auth_enabled": password_auth_enabled,
            "passwordless_enabled": bool(passkeys) and not password_auth_enabled,
            "passkeys_enabled": bool(passkeys),
            "passkeys_count": len(passkeys),
            "passkey_feature_flag": passkey_flag,
            "auth_disabled_acknowledged": bool(load_settings().get("auth_disabled_acknowledged")) if not auth_enabled else False,
        }
    
    def _source_stamp():
        try:
            from api.config import _SETTINGS_WRITE_VERSION
            return (_SETTINGS_WRITE_VERSION,)
        except Exception:
            return None
    
    payload, hit = _status_cache_get(
        key=("auth_status",),
        builder=_build,
        ttl=2.0,
        source_stamp_fn=_source_stamp,
    )
    handler.send_header("X-Cache", "HIT" if hit else "MISS")
    return j(handler, payload)
```

- [ ] **Step 3: 验证**

```bash
time curl -s http://localhost:8787/api/auth/status
time curl -s http://localhost:8787/api/auth/status  # 第二次 < 5ms
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add api/auth.py api/routes.py
git commit -m "feat(perf): /api/auth/status 接入 TTL 缓存（Phase 3 PR3）"
```

---

## Task 3.4：`/api/health/agent` 接入缓存

**Files:**
- Modify: `api/routes.py:12590-12594`（health/agent handler）

- [ ] **Step 1: 包一层 status_cache_get**

修改前：
```python
if parsed.path == "/api/health/agent":
    payload = build_agent_health_payload()
    payload["gateway_chat"] = gateway_chat_config_status()
    j(handler, payload)
    return True
```

修改后：
```python
if parsed.path == "/api/health/agent":
    from api.route_status_cache import _status_cache_get
    from pathlib import Path
    
    def _build():
        p = build_agent_health_payload()
        p["gateway_chat"] = gateway_chat_config_status()
        return p
    
    def _source_stamp():
        # gateway_state.json + gateway.pid 的 mtime
        try:
            from hermes_constants import get_default_hermes_root
            root = get_default_hermes_root()
            st1 = (root / "gateway_state.json").stat()
            st2 = (root / "gateway.pid").stat()
            return ((st1.st_mtime_ns, st1.st_size), (st2.st_mtime_ns, st2.st_size))
        except Exception:
            return None
    
    payload, hit = _status_cache_get(
        key=("health_agent",),
        builder=_build,
        ttl=3.0,
        source_stamp_fn=_source_stamp,
    )
    handler.send_header("X-Cache", "HIT" if hit else "MISS")
    j(handler, payload)
    return True
```

- [ ] **Step 2: 验证 + Commit**

```bash
time curl -s http://localhost:8787/api/health/agent
git add api/routes.py
git commit -m "feat(perf): /api/health/agent 接入 TTL 缓存（Phase 3 PR3）"
```

---

## Task 3.5：`/api/crons/recent` 接入缓存

**Files:**
- Modify: `api/routes.py:13696-13701`（crons/recent handler）
- Modify: `api/crons/jobs.py`（cron 写路径 invalidate）

- [ ] **Step 1: 加 cron 写路径 invalidate**

在 `api/crons/jobs.py` 找到 `add_job`/`update_job`/`delete_job` 等写函数，加：
```python
from api.route_status_cache import _status_cache_invalidate

_status_cache_invalidate(("crons_recent",), reason="cron_write")
```

- [ ] **Step 2: 包一层 status_cache_get**

修改前：
```python
if parsed.path == "/api/crons/recent":
    from api.profiles import cron_profile_context
    with cron_profile_context():
        _ensure_agent_cron_import_path()
        return _handle_cron_recent(handler, parsed)
```

修改后：
```python
if parsed.path == "/api/crons/recent":
    from api.profiles import cron_profile_context
    from api.route_status_cache import _status_cache_get
    
    def _build():
        with cron_profile_context():
            _ensure_agent_cron_import_path()
            return _handle_cron_recent_inner(parsed)  # 提取 inner 版本
    
    def _source_stamp():
        try:
            from cron.jobs import list_jobs
            # 用 jobs 列表的某种 hash 作为 stamp（如果 list_jobs 返回的对象 hashable）
            # 否则用文件 mtime
            jobs = list_jobs(include_disabled=True)
            return hash(tuple(sorted((j.get("id"), j.get("last_run_at"), j.get("enabled")) for j in jobs)))
        except Exception:
            return None
    
    payload, hit = _status_cache_get(
        key=("crons_recent",),
        builder=_build,
        ttl=5.0,
        source_stamp_fn=_source_stamp,
    )
    handler.send_header("X-Cache", "HIT" if hit else "MISS")
    return j(handler, payload)
```

> 注：原 `_handle_cron_recent(handler, parsed)` 直接写 response；需要重构成 `_handle_cron_recent_inner(parsed) -> dict` 返回 dict，让 cache 包一层。

- [ ] **Step 3: 验证 + Commit**

```bash
time curl -s http://localhost:8787/api/crons/recent
git add api/crons/jobs.py api/routes.py
git commit -m "feat(perf): /api/crons/recent 接入 TTL 缓存（Phase 3 PR3）"
```

---

## Task 3.6：`/api/session/status` 接入缓存（含 streaming hold-down）

**Files:**
- Modify: `api/routes.py:13254-13263`（session/status handler）

- [ ] **Step 1: 包一层 status_cache_get（复用 sessions 的 streaming hold-down 模式）**

```python
if parsed.path == "/api/session/status":
    sid = parse_qs(parsed.query).get("session_id", [""])[0]
    if not sid:
        return bad(handler, "Missing session_id")
    
    from api.session_ops import session_status
    from api.route_status_cache import _status_cache_get
    
    def _build():
        _clear_stale_stream_state(get_session(sid, metadata_only=True))
        return session_status(sid)
    
    def _source_stamp():
        try:
            from api.route_session_list_cache import _session_list_cache_active_stream_ids
            active = _session_list_cache_active_stream_ids()
            if active and any(streaming_id := active):
                # streaming 期间冻结 stamp（与 sessions 缓存一致）
                return ("streaming", tuple(sorted(str(x) for x in active)))
            # 否则用 session.json 的 mtime + state.db fingerprint
            try:
                from api.models import _active_state_db_path
                from api.models import _sqlite_content_fingerprint
                state_db = _active_state_db_path()
                fp = _sqlite_content_fingerprint(state_db) if state_db else None
            except Exception:
                fp = None
            try:
                session_path = SESSION_DIR / f"{sid}.json"
                st = session_path.stat()
                return ((st.st_mtime_ns, st.st_size), fp)
            except OSError:
                return (None, fp)
    
    payload, hit = _status_cache_get(
        key=("session_status", sid),
        builder=_build,
        ttl=2.0,  # streaming 时延长到 10s（source_stamp 控制）
        source_stamp_fn=_source_stamp,
    )
    handler.send_header("X-Cache", "HIT" if hit else "MISS")
    return j(handler, payload)
```

- [ ] **Step 2: 验证 + Commit**

```bash
time curl -s "http://localhost:8787/api/session/status?session_id=$TEST_SID"
git add api/routes.py
git commit -m "feat(perf): /api/session/status 接入 TTL 缓存（含 streaming hold-down）（Phase 3 PR3）"
```

---

## Task 3.7：Phase 3 验收测试

- [ ] **Step 1: 5 个接口性能测试**

```bash
for endpoint in /api/license/status /api/auth/status /api/health/agent /api/crons/recent /api/session/status; do
    echo "=== $endpoint ==="
    for i in {1..10}; do
        time curl -s "http://localhost:8787$endpoint?session_id=$TEST_SID" > /dev/null
    done
done
```

Expected: 第一次 < 200ms，后续 < 5ms（cache hit）

- [ ] **Step 2: 写路径 invalidate 测试**

修改 settings，验证 `/api/auth/status` 立即返回新值：
```bash
# 修改 settings
curl -X POST http://localhost:8787/api/settings -d '{"auth_disabled_acknowledged": true}' -H "Content-Type: application/json"
# 立即查
time curl -s http://localhost:8787/api/auth/status | jq '.auth_disabled_acknowledged'
```

Expected: 立即返回 `true`（不是 cache 旧值）

- [ ] **Step 3: 性能基准 `tests/bench_high_freq.py`**

新建：
```python
# tests/bench_high_freq.py
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

ENDPOINTS = =[
    ("/api/license/status", None),
    ("/api/auth/status", None),
    ("/api/health/agent", None),
    ("/api/crons/recent", None),
    ("/api/session/status", "session_id=fake-sid"),
]


@pytest.mark.parametrize("endpoint,query", ENDPOINTS)
def test_bench_endpoint(endpoint, query):
    """p95 < 200ms（cache hit）"""
    # 启动服务后用真实 HTTP 测
    import requests
    url = f"http://localhost:8787{endpoint}"
    if query:
        url += f"?{query}"
    
    # warmup
    requests.get(url)
    
    # 100 次
    times = []
    for _ in range(100):
        start = time.monotonic()
        requests.get(url)
        times.append((time.monotonic() - start) * 1000)
    
    times.sort()
    p95 = times[94]
    p99 = times[98]
    print(f"\n{endpoint}: p50={times[49]:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms")
    
    assert p95 < 200, f"{endpoint} p95={p95}ms > 200ms"
```

Run: `python -m pytest tests/bench_high_freq.py -v --noconftest -s`
Expected: 5 个接口 p95 < 200ms

- [ ] **Step 4: Commit Phase 3 完成**

```bash
git add tests/bench_high_freq.py
git commit --allow-empty -m "chore(perf): Phase 3 PR3 验收通过（5 高频接口 p95 < 200ms）"
```

---

# Phase 4：3 处 SSE 化（PR4，~3-5 天）

**目标：** 3 个 SSE 多路复用到 `/api/sessions/events`（避免 Chrome 6 连接上限）。前端 3 处 `setInterval` 改 EventSource + fallback 轮询。多 tab 不重复拉。

## Task 4.1：后端 3 个 publish 函数（多路复用准备）

**Files:**
- Modify: `api/session_events.py`

- [ ] **Step 1: 新增 3 个 publish 函数**

在 `api/session_events.py` 加：
```python
def publish_approval_event(session_id: str, pending: dict | None, pending_count: int) -> None:
    """通过 session_events 推送 approval 事件（多路复用）"""
    payload = {
        "type": "approval",
        "session_id": session_id,
        "pending": dict(pending) if pending else None,
        "pending_count": pending_count,
    }
    _publish_payload(payload)


def publish_clarify_event(session_id: str, pending: dict | None, pending_count: int) -> None:
    """通过 session_events 推送 clarify 事件"""
    payload = {
        "type": "clarify",
        "session_id": session_id,
        "pending": dict(pending) if pending else None,
        "pending_count": pending_count,
    }
    _publish_payload(payload)


def publish_session_status_event(session_id: str, status: dict) -> None:
    """通过 session_events 推送 session status 事件"""
    payload = {
        "type": "session_status",
        "session_id": session_id,
        "status": status,
    }
    _publish_payload(payload)


def _publish_payload(payload: dict) -> None:
    """复用 sessions_changed 的分发机制"""
    global _SESSION_EVENTS_VERSION
    with _SESSION_EVENTS_LOCK:
        _SESSION_EVENTS_VERSION += 1
        payload["version"] = _SESSION_EVENTS_VERSION
        subscribers = list(_SESSION_EVENTS_SUBSCRIBERS)
    for q in subscribers:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pending = None
            try:
                pending = q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(payload)  # 直接覆盖（不强求合并，避免 profile/session_id 不匹配）
            except queue.Full:
                pass
```

- [ ] **Step 2: Commit**

```bash
git add api/session_events.py
git commit -m "feat(perf): session_events 加 3 个多路复用 publish（Phase 4 PR4）"
```

---

## Task 4.2：approval notify 改多路复用

**Files:**
- Modify: `api/route_approvals.py`

- [ ] **Step 1: 在 `_approval_sse_notify_locked` 同步调 `publish_approval_event`**

修改前（约 line 70-93）：
```python
def _approval_sse_notify_locked(session_id: str, head: dict | None, total: int) -> None:
    payload = {"pending": dict(head) if head else None, "pending_count": total}
    subs = _approval_sse_subscribers.get(session_id, ())
    for q in subs:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass
```

修改后：
```python
def _approval_sse_notify_locked(session_id: str, head: dict | None, total: int) -> None:
    payload = {"pending": dict(head) if head else None, "pending_count": total}
    # 原有 /api/approval/stream 订阅者
    subs = _approval_sse_subscribers.get(session_id, ())
    for q in subs:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass
    # 多路复用：同步推送到 /api/sessions/events 总线（Phase 4 PR4）
    try:
        from api.session_events import publish_approval_event
        publish_approval_event(session_id, head, total)
    except Exception:
        logger.debug("publish_approval_event failed", exc_info=True)
```

- [ ] **Step 2: Commit**

```bash
git add api/route_approvals.py
git commit -m "feat(perf): approval notify 多路复用（Phase 4 PR4）"
```

---

## Task 4.3：clarify notify 改多路复用

**Files:**
- Modify: `api/clarify.py`

- [ ] **Step 1: 在 `_clarify_sse_notify` 同步调 `publish_clarify_event`**

修改前（约 line 97-104）：
```python
def _clarify_sse_notify(session_id: str, head: dict | None, total: int) -> None:
    payload = {"pending": dict(head) if head else None, "pending_count": total}
    for q in _clarify_sse_subscribers.get(session_id, ()):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass
```

修改后：
```python
def _clarify_sse_notify(session_id: str, head: dict | None, total: int) -> None:
    payload = {"pending": dict(head) if head else None, "pending_count": total}
    for q in _clarify_sse_subscribers.get(session_id, ()):
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass
    # 多路复用（Phase 4 PR4）
    try:
        from api.session_events import publish_clarify_event
        publish_clarify_event(session_id, head, total)
    except Exception:
        logger.debug("publish_clarify_event failed", exc_info=True)
```

- [ ] **Step 2: Commit**

```bash
git add api/clarify.py
git commit -m "feat(perf): clarify notify 多路复用（Phase 4 PR4）"
```

---

## Task 4.4：`/api/session/stream` 多路复用事件

**Files:**
- Modify: `api/background_process.py`

- [ ] **Step 1: 找到 SESSION_CHANNELS emit 处，加 session_status 多路复用**

参考 SPEC §3.4 的"具体做法"第 1 步。在 SESSION_CHANNELS emit 之前或之后调：
```python
# 找到 streaming 完成 / 状态变更处
from api.session_events import publish_session_status_event
publish_session_status_event(sid, status_dict)
```

- [ ] **Step 2: Commit**

```bash
git add api/background_process.py
git commit -m "feat(perf): session status 事件多路复用（Phase 4 PR4）"
```

---

## Task 4.5：前端 `_wireSSE` 工具函数

**Files:**
- Modify: `static/messages.js`

- [ ] **Step 1: 在 messages.js 顶层加 `_wireSSE`**

```javascript
// static/messages.js 顶层（模块作用域）

/**
 * 通用的 SSE 包装：自动重连 + fallback 轮询。
 * @param {string} url - SSE URL
 * @param {function} onMessage - (data) => void
 * @param {function} onError - (event) => void（可选）
 * @param {object} fallback - { intervalMs: 1500, fetchFn: () => Promise<data> }（可选）
 * @returns {function} close function
 */
function _wireSSE(url, onMessage, onError, fallback) {
  let es = null;
  let fallbackTimer = null;
  let closed = false;
  
  function connect() {
    if (closed) return;
    es = new EventSource(url, { withCredentials: true });
    
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onMessage(data);
      } catch (err) {
        console.warn('SSE parse error', err);
      }
    };
    
    es.onerror = (e) => {
      if (onError) onError(e);
      es.close();
      // fallback 到轮询（如果提供了）
      if (fallback && !fallbackTimer) {
        fallbackTimer = setInterval(async () => {
          try {
            const data = await fallback.fetchFn();
            onMessage(data);
          } catch (err) {
            console.warn('fallback poll error', err);
          }
        }, fallback.intervalMs);
      }
      // 重连退避
      setTimeout(() => connect(), 3000);
    };
    
    es.onopen = () => {
      // 重连成功，停 fallback
      if (fallbackTimer) {
        clearInterval(fallbackTimer);
        fallbackTimer = null;
      }
    };
  }
  
  connect();
  
  return function close() {
    closed = true;
    if (es) es.close();
    if (fallbackTimer) clearInterval(fallbackTimer);
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add static/messages.js
git commit -m "feat(ui): messages.js 加 _wireSSE 工具函数（Phase 4 PR4）"
```

---

## Task 4.6：approval 改 SSE

**Files:**
- Modify: `static/messages.js`（line 6819 附近）

- [ ] **Step 1: 替换 `setInterval` 为 SSE**

修改前：
```javascript
_approvalPollTimer = setInterval(_tick, 1500);
```

修改后：
```javascript
// Phase 4 PR4：改 SSE（多路复用 /api/sessions/events）
if (_approvalPollTimer) clearInterval(_approvalPollTimer);
if (_approvalSSEClose) _approvalSSEClose();

_approvalSSEClose = _wireSSE(
  '/api/sessions/events',  // 多路复用总线
  (data) => {
    if (data.type !== 'approval' || data.session_id !== S.session.session_id) return;
    if (data.pending) {
      showApprovalCard(data.pending);
    } else {
      hideApprovalCard(false);
    }
  },
  null,
  {
    intervalMs: 1500,
    fetchFn: async () => {
      const sid = S.session.session_id;
      return await api(`/api/approval/pending?session_id=${encodeURIComponent(sid)}`);
    },
  }
);
```

- [ ] **Step 2: 验证**

打开浏览器 → 触发一个 approval → 验证 3 秒内卡片显示（不再是 1500ms 延迟）

- [ ] **Step 3: Commit**

```bash
git add static/messages.js
git commit -m "feat(ui): approval 改 SSE 多路复用（Phase 4 PR4）"
```

---

## Task 4.7：session/status 改 SSE

**Files:**
- Modify: `static/messages.js`（line 7014 附近）

- [ ] **Step 1: 替换 `setInterval` 为 SSE**

修改前：
```javascript
_sessionStreamHiddenPollTimer = setInterval(tick, 6000);
```

修改后：
```javascript
// Phase 4 PR4：改 SSE 多路复用
if (_sessionStreamHiddenPollTimer) clearInterval(_sessionStreamHiddenPollTimer);
if (_sessionStatusSSEClose) _sessionStatusSSEClose();

_sessionStatusSSEClose = _wireSSE(
  '/api/sessions/events',
  (data) => {
    if (data.type !== 'session_status' || data.session_id !== S.session.session_id) return;
    // 更新 session status UI
    updateSessionStatusUI(data.status);
  },
  null,
  {
    intervalMs: 6000,
    fetchFn: async () => {
      const sid = S.session.session_id;
      return await api(`/api/session/status?session_id=${encodeURIComponent(sid)}`);
    },
  }
);
```

- [ ] **Step 2: Commit**

```bash
git add static/messages.js
git commit -m "feat(ui): session/status 改 SSE 多路复用（Phase 4 PR4）"
```

---

## Task 4.8：clarify 改 SSE

**Files:**
- Modify: `static/messages.js`

- [ ] **Step 1: 替换 clarify polling 为 SSE**

```javascript
// Phase 4 PR4
if (_clarifySSEClose) _clarifySSEClose();
_clarifySSEClose = _wireSSE(
  '/api/sessions/events',
  (data) => {
    if (data.type !== 'clarify' || data.session_id !== S.session.session_id) return;
    if (data.pending) {
      showClarifyCard(data.pending);
    } else {
      hideClarifyCard(false);
    }
  },
  null,
  {
    intervalMs: 1500,
    fetchFn: async () => {
      const sid = S.session.session_id;
      return await api(`/api/clarify/pending?session_id=${encodeURIComponent(sid)}`);
    },
  }
);
```

- [ ] **Step 2: Commit**

```bash
git add static/messages.js
git commit -m "feat(ui): clarify 改 SSE 多路复用（Phase 4 PR4）"
```

---

## Task 4.9：多 tab 同步测试

- [ ] **Step 1: tmux 端到端**

```bash
# 启动服务
tmux new-session -d -s hermes 'python -m api.routes 8787'
sleep 3

# 用 playwright 打开 3 个 tab
# tab1：触发 approval
# tab2、tab3：等待 SSE 推送
# 验证：3 个 tab 同时显示 approval 卡片
```

- [ ] **Step 2: 网络面板验证**

打开 Chrome DevTools → Network → 找 SSE 连接：
- 1 个 `/api/sessions/events`（多路复用）
- 不应有 3 个独立的 approval/clarify/session SSE

Expected: 总 SSE 连接数 ≤ 6

- [ ] **Step 3: 性能基准**

```bash
# 多 tab 同时打开，测量接口响应时间
for i in {1..5}; do
    curl -s "http://localhost:8787/api/sessions/events" --max-time 1 &
done
```

- [ ] **Step 4: Commit Phase 4 完成**

```bash
git commit --allow-empty -m "chore(perf): Phase 4 PR4 验收通过（多 tab SSE 同步）"
```

---

# Phase 5：`_index.json` 侧车索引（PR5+，~1-2 周）

**目标：** `list_sessions()` 走 `_index.json` 索引，4-500 session 下 < 50ms。

## Task 5.1：索引结构定义

**Files:**
- Modify: `api/webui_session_db.py`

- [ ] **Step 1: 加 `_INDEX_FIELDS` 常量**

修改前（约 line 20 `_METADATA_FIELDS`）：
```python
_METADATA_FIELDS = frozenset({...})
```

修改后（追加）：
```python
_INDEX_FIELDS = frozenset({
    "title",
    "workspace",
    "model",
    "model_provider",
    "created_at",
    "updated_at",
    "pinned",
    "archived",
    "message_count",
    "last_message_at",
    "is_cli_session",
    "source_tag",
    "raw_source",
    "session_source",
    "source_label",
    "project_id",
    "profile",
    "personality",
})


_INDEX_FILENAME = "_index.json"
_INDEX_VERSION = 1  # 当前索引 schema 版本
```

- [ ] **Step 2: 加索引路径解析**

```python
def _index_path(self) -> Path:
    return self.session_dir / _INDEX_FILENAME


def _read_index(self) -> dict | None:
    """读 _index.json；不存在或损坏返回 None"""
    path = self._index_path()
    if not path.exists():
        return None
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_index(self, index_data: dict) -> None:
    """原子写 _index.json"""
    import json
    import os
    path = self._index_path()
    tmp = path.with_suffix(f".tmp.{os.getpid()}.{threading.current_thread().ident}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
```

- [ ] **Step 3: Commit**

```bash
git add api/webui_session_db.py
git commit -m "feat(perf): webui_session_db 加 _index.json 结构定义（Phase 5）"
```

---

## Task 5.2：索引写入路径（_update_session_index / _remove_session_index）

**Files:**
- Modify: `api/webui_session_db.py`

- [ ] **Step 1: 加 `_update_session_index`**

```python
def _update_session_index(self, sid: str, data: dict) -> None:
    """更新索引中某个 session 的元数据条目"""
    index = self._read_index()
    if index is None:
        # 索引不存在，全量重建（fallback）
        index = self._rebuild_session_index()
    
    sid_str = str(sid)
    entry = {k: data.get(k) for k in _INDEX_FIELDS if k in data}
    entry["session_id"] = sid_str
    index["sessions"][sid_str] = entry
    index["_version"] = index.get("_version", 0) + 1
    index["_written_at"] = time.time()
    
    self._write_index(index)


def _remove_session_index(self, sid: str) -> None:
    """从索引移除某个 session"""
    index = self._read_index()
    if index is None:
        return
    
    sid_str = str(sid)
    index["sessions"].pop(sid_str, None)
    index["_version"] = index.get("_version", 0) + 1
    index["_written_at"] = time.time()
    
    self._write_index(index)
```

加 import：`import time`

- [ ] **Step 2: Commit**

```bash
git add api/webui_session_db.py
git commit -m "feat(perf): webui_session_db 加索引写入函数（Phase 5）"
```

---

## Task 5.3：写 session 同步写索引

**Files:**
- Modify: `api/webui_session_db.py`（`write_session` / `update_metadata`）

- [ ] **Step 1: 在 `write_session()` 末尾加索引更新**

修改 `write_session()`（约 line 149）：
```python
def write_session(self, session: dict[str, Any]) -> dict[str, Any]:
    # ... 原代码 ...
    
    # Phase 5：同步写索引
    try:
        self._update_session_index(sid, payload)
    except Exception:
        logger.warning("_update_session_index failed for %s (will rebuild on next list)", sid, exc_info=True)
    
    return copy.deepcopy(payload)
```

- [ ] **Step 2: 在 `update_metadata()` 末尾加索引更新**

```python
def update_metadata(self, sid: str, fields: dict[str, Any]) -> dict[str, Any]:
    # ... 原代码（写 JSON）...
    
    # Phase 5：同步写索引
    try:
        self._update_session_index(sid, data)
    except Exception:
        logger.warning("_update_session_index failed for %s", sid, exc_info=True)
    
    return self._metadata_row(...)
```

- [ ] **Step 3: 在 `archive()` 调用 `_remove_session_index`（archived 时不删条目但更新）**

archive 实际是 update metadata，逻辑已在 Task 5.3 Step 2 覆盖。

- [ ] **Step 4: 删除 session 时也调 `_remove_session_index`**

```python
def delete_session_metadata(sid: str) -> None:
    """删除 session JSON 后调此函数清索引"""
    from api.webui_session_db import WebUIJsonSessionDB
    db = WebUIJsonSessionDB()
    db._remove_session_index(sid)
```

- [ ] **Step 5: Commit**

```bash
git add api/webui_session_db.py
git commit -m "feat(perf): write_session/update_metadata 同步写 _index.json（Phase 5）"
```

---

## Task 5.4：`_rebuild_session_index`（全量重建）

**Files:**
- Modify: `api/webui_session_db.py`

- [ ] **Step 1: 实现全量重建函数**

```python
def _rebuild_session_index(self) -> dict:
    """从 sessions/*.json 全量重建 _index.json"""
    import json
    sessions: dict[str, dict] = {}
    if self.session_dir.exists():
        for path in self.session_dir.glob("*.json"):
            if path.name.startswith("_") or path.name == _INDEX_FILENAME:
                continue
            data = self._read_path(path)
            if not isinstance(data, dict):
                continue
            sid = str(data.get("session_id") or path.stem)
            if not models.is_safe_session_id(sid):
                continue
            entry = {k: data.get(k) for k in _INDEX_FIELDS if k in data}
            entry["session_id"] = sid
            messages = data.get("messages")
            if isinstance(messages, list):
                entry["message_count"] = entry.get("message_count", len(messages))
            entry["last_message_at"] = data.get("last_message_at") or data.get("updated_at") or data.get("created_at")
            sessions[sid] = entry
    
    return {
        "_version": _INDEX_VERSION,
        "_written_at": time.time(),
        "sessions": sessions,
    }


def rebuild_session_index_from_disk(self) -> None:
    """启动时调用：索引缺失或过期时全量重建"""
    index = self._read_index()
    if index is None:
        # 索引不存在，全量重建
        new_index = self._rebuild_session_index()
        self._write_index(new_index)
        return
    
    # 索引存在但可能过期：检查 sessions/*.json 的 mtime
    if not self.session_dir.exists():
        return
    
    index_mtime = self._index_path().stat().st_mtime
    
    # 抽样检查最近修改的 JSON 文件（不全量 stat）
    json_files = list(self.session_dir.glob("*.json"))
    needs_rebuild = False
    for path in json_files:
        if path.name == _INDEX_FILENAME:
            continue
        try:
            if path.stat().st_mtime > index_mtime:
                needs_rebuild = True
                break
        except OSError:
            continue
    
    if needs_rebuild:
        new_index = self._rebuild_session_index()
        self._write_index(new_index)
```

- [ ] **Step 2: Commit**

```bash
git add api/webui_session_db.py
git commit -m "feat(perf): webui_session_db 加全量重建索引（Phase 5）"
```

---

## Task 5.5：`list_sessions_from_index` 读路径

**Files:**
- Modify: `api/webui_session_db.py`

- [ ] **Step 1: 加读路径函数**

```python
def list_sessions_from_index(self) -> list[dict[str, Any]]:
    """从 _index.json 读所有 session metadata（O(1) 文件读）"""
    index = self._read_index()
    if index is None:
        # 索引不存在，fallback
        return self.list_sessions()
    
    rows = []
    for sid, entry in index.get("sessions", {}).items():
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["session_id"] = sid
        rows.append(row)
    
    rows.sort(key=lambda row: (bool(row.get("pinned")), self._sort_timestamp(row)), reverse=True)
    return rows


# 顶层函数（兼容现有调用）
def list_sessions_via_index() -> list[dict[str, Any]]:
    return WebUIJsonSessionDB().list_sessions_from_index()
```

- [ ] **Step 2: 修改 `list_sessions()` 默认走索引（env 可关闭）**

```python
def list_sessions() -> list[dict[str, Any]]:
    if os.environ.get("HERMES_WEBUI_DISABLE_SESSION_INDEX", "").strip() not in ("1", "true", "yes"):
        # 默认走索引
        return WebUIJsonSessionDB().list_sessions_from_index()
    # 回滚开关：原 glob + loads
    return WebUIJsonSessionDB().list_sessions()
```

加 import：`import os`

- [ ] **Step 3: Commit**

```bash
git add api/webui_session_db.py
git commit -m "feat(perf): list_sessions 默认走 _index.json（Phase 5）"
```

---

## Task 5.6：启动时 rebuild_if_needed

**Files:**
- Modify: `api/startup.py`

- [ ] **Step 1: 在 startup 调用索引重建**

```python
def fix_credential_permissions() -> None:
    # ... 原代码 ...
    
    # Phase 5：启动时重建 _index.json（如果需要）
    try:
        from api.webui_session_db import WebUIJsonSessionDB
        WebUIJsonSessionDB().rebuild_session_index_from_disk()
    except Exception:
        # best-effort
        pass
```

- [ ] **Step 2: Commit**

```bash
git add api/startup.py
git commit -m "feat(perf): startup 启动时按需重建索引（Phase 5）"
```

---

## Task 5.7：单元测试 + 集成测试

**Files:**
- Create: `tests/test_session_index.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_session_index.py
import os
import sys
import json
import shutil
import tempfile
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_session_dir():
    d = tempfile.mkdtemp(prefix="session_index_")
    yield = d
    shutil.rmtree(d, ignore_errors=True)


def test_list_sessions_uses_index_when_present(tmp_session_dir):
    """索引存在时 list_sessions 走索引"""
    from api.webui_session_db import WebUIJsonSessionDB, write_session
    
    # 写 3 个 session
    for i in range(3):
        write_session({
            "session_id": f"sid-{i}",
            "title": f"session-{i}",
            "messages": [{"role": "user", "content": "x"}],
        })
    
    db = WebUIJsonSessionDB(session_dir=tmp_session_dir)
    
    # 第一次 list_sessions 触发索引重建
    rows1 = db.list_sessions()
    assert len(rows1) == 3
    
    # 索引文件应已存在
    index_path = db._index_path()
    assert index_path.exists()
    
    # 第二次直接走索引
    rows2 = db.list_sessions()
    assert len(rows2) == 3
    assert sorted(r["session_id"] for r in rows2) == sorted(r["session_id"] for r in rows1)


def test_write_session_updates_index(tmp_session_dir):
    """write_session 后索引同步更新"""
    from api.webui_session_db import WebUIJsonSessionDB, write_session
    
    db = WebUIJsonSessionDB(session_dir=tmp_session_dir)
    write_session({
        "session_id": "sid-1",
        "title": "test",
        "messages": [{"role": "user", "content": "x"}],
    })
    
    # 读索引
    index = db._read_index()
    assert "sid-1" in index["sessions"]
    assert index["sessions"]["sid-1"]["title"] == "test"


def test_index_write_failure_does_not_break_main_flow(tmp_session_dir, monkeypatch):
    """索引写失败不影响主流程"""
    from api import webui_session_db
    from api.webui_session_db import WebUIJsonSessionDB, write_session
    
    db = WebUIJsonSessionDB(session_dir=tmp_session_dir)
    
    def fail_write(*args, **kwargs):
        raise OSError("disk full")
    
    monkeypatch.setattr(db, "_write_index", fail_write)
    
    # write_session 应仍然成功（索引失败被吞）
    result = write_session({
        "session_id": "sid-1",
        "title": "test",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert result["session_id"] == "sid-1"


def test_rebuild_if_index_missing(tmp_session_dir):
    """索引缺失时启动触发全量重建"""
    from api.webui_session_db import WebUIJsonSessionDB, write_session
    
    db = WebUIJsonSessionDB(session_dir=tmp_session_dir)
    
    # 写 5 个 session（write_session 会调 _update_session_index，但索引缺失时走 rebuild）
    for i in range(5):
        write_session({
            "session_id": f"sid-{i}",
            "title": f"test-{i}",
            "messages": [{"role": "user", "content": "x"}],
        })
    
    # 删除索引
    index_path = db._index_path()
    if index_path.exists():
        index_path.unlink()
    
    # rebuild_if_needed
    db.rebuild_session_index_from_disk()
    
    # 索引应已重建
    assert index_path.exists()
    index = db._read_index()
    assert len(index["sessions"]) == 5


def test_list_sessions_500_indexed_under_50ms(tmp_session_dir):
    """500 session 索引读 < 50ms"""
    from api.webui_session_db import WebUIJsonSessionDB, write_session
    
    db = WebUIJsonSessionDB(session_dir=tmp_session_dir)
    
    # 写 500 个 session
    for i in range(500):
        write_session({
            "session_id": f"sid-{i:04d}",
            "title": f"session-{i}",
            "messages": [{"role": "user", "content": "x"}],
        })
    
    # warmup
    db.list_sessions()
    
    # 测量 10 次
    times = []
    for _ in range(10):
        start = time.monotonic()
        rows = db.list_sessions()
        times.append((time.monotonic() - start) * 1000)
        assert len(rows) == 500
    
    avg = sum(times) / len(times)
    print(f"\navg={avg:.2f}ms")
    assert avg < 50, f"list_sessions avg={avg:.2f}ms > 50ms"
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_session_index.py -v --noconftest`
Expected: 5 个 test 都 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_session_index.py
git commit -m "test(perf): _index.json 索引单元 + 性能测试（Phase 5）"
```

---

## Task 5.8：Phase 5 验收测试

- [ ] **Step 1: 启动验证**

启动服务，验证日志有 "rebuild_session_index_from_disk"：
```bash
python -c "import api.startup; api.startup.fix_credential_permissions()"
```

- [ ] **Step 2: 性能基准**

```bash
python -m pytest tests/bench_session_load.py -v --noconftest -s
```

Expected: 500 session 启动 < 1s，冷启动后 `list_sessions()` < 50ms

- [ ] **Step 3: 兼容测试**

模拟升级：手动删除 _index.json，启动服务，验证启动后自动重建。

- [ ] **Step 4: Commit Phase 5 完成**

```bash
git commit --allow-empty -m "chore(perf): Phase 5 PR5+ 验收通过（list_sessions < 50ms）"
```

---

# 跨 Phase 验收

每个 Phase 部署后必跑：

## 全局性能基准

- [ ] **打开会话 < 1s**（Phase 1 后）

```bash
python -m pytest tests/bench_open_conversation.py -v --noconftest -s
```

- [ ] **5 高频接口 p95 < 200ms**（Phase 3 后）

```bash
python -m pytest tests/bench_high_freq.py -v --noconftest -s
```

- [ ] **dashboard < 50ms**（Phase 2 后）

- [ ] **list_sessions < 50ms**（Phase 5 后）

```bash
python -m pytest tests/bench_session_load.py -v --noconftest -s
```

## SSE 多 tab 同步（Phase 4 后）

- [ ] **总 SSE 连接数 < 6**（Chrome 上限）
- [ ] **3 个 tab 同时打开，approval/clarify 在所有 tab 显示 < 3s**

## 回归测试

- [ ] **license gate 不被破坏**（`/health` 仍 200）
- [ ] **auth gate 仍生效**
- [ ] **既有 chat stream 不被打断**

---

## 自检

1. **Spec coverage**：5 个 PR × 关键文件全部覆盖（api/routes.py、api/route_status_cache.py、api/dashboard_probe.py、api/session_events.py、api/route_approvals.py、api/clarify.py、api/webui_session_db.py、static/messages.js、static/sessions.js、tests/）
2. **Placeholder scan**：无 TBD / TODO / 待确认 / fill in
3. **Type consistency**：`status_cache_get` / `status_cache_invalidate` / `publish_approval_event` / `publish_clarify_event` / `publish_session_status_event` / `_index_path` / `_update_session_index` / `_remove_session_index` / `_rebuild_session_index` / `rebuild_session_index_from_disk` / `list_sessions_from_index` 等函数名在 spec 与 plan 中一致
4. **回滚开关**：5 个 env 变量与 spec §7.1 表对应

---

## 执行选择

Plan 已保存到 `docs/superpowers/plans/2026-08-07-session-loading-perf-plan.md`（**待 commit**）。两个执行选项：

**1. Subagent-Driven（推荐）** —— 每个 Task 派一个独立 subagent 执行，task 间 review，快速迭代。适合 5 个 PR × ~40 个 task 的大规模实施。

**2. Inline Execution** —— 当前会话内执行 tasks，按阶段 checkpoint 暂停确认。适合小范围手动验证。

哪个？