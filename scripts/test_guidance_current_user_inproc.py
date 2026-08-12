"""In-process HTTP 集成测试 — 验证 bug 1 修复（current_user 出现在 GET 响应里）。

不依赖 pytest conftest 的 test_server fixture（那个 fixture 要 bind 端口，沙箱/CI 不一定放行）。
用 socketpair 走完整的 server.Handler → api.routes → api.guidance_http.handle_guidance_get 路径。

用法：
  PYTHONPATH=. python3 scripts/test_guidance_current_user_inproc.py

退出码 0 = 全过，非 0 = 失败。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    TD = tempfile.mkdtemp(prefix="hermes-guidance-inproc-")
    fake_home = Path(TD) / "hermes"
    fake_home.mkdir()
    state_dir = Path(TD) / "state"
    state_dir.mkdir()
    workspace = state_dir / "workspace"
    workspace.mkdir()

    os.environ.update({
        "HERMES_HOME": str(fake_home),
        "HERMES_WEBUI_STATE_DIR": str(state_dir),
        "HERMES_WEBUI_DEFAULT_WORKSPACE": str(workspace),
        "HERMES_WEBUI_TEST_NETWORK_BLOCK": "1",
    })

    from api import guidance_progress as gp
    from api import asset_inventory as ai
    gp.get_active_hermes_home = lambda: fake_home
    ai.get_active_hermes_home = lambda: fake_home

    # Inject a valid license so the license gate allows the request.
    license_dir = workspace / ".license"
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / "license.json").write_text(json.dumps({
        "activated": True,
        "expires_at": "2099-12-31T00:00:00Z",
        "imported_at": "2026-01-01T00:00:00Z",
    }))

    # Stub auth so we don't have to set up real sessions / RBAC users.
    import api.guidance_http as ghttp
    ghttp._current_user = lambda handler: {"id": "u-alice", "username": "alice", "role": "admin"}
    ghttp._current_username = lambda handler: "alice"
    ghttp._require_admin_or_ops = lambda handler: None

    from server import Handler as HermesHandler

    class _PairedServer:
        address_family = socket.AF_INET
        server_address = ("socketpair", 0)

        def __init__(self, s):
            self.client_sock = s

        def get_request(self):
            return self.client_sock, ("in-process", 0)

        def close_request(self, r):
            try:
                r.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            r.close()

        def server_bind(self):
            pass

        def server_activate(self):
            pass

        def verify_request(self, r, c):
            return True

        def server_close(self):
            pass

    def http_request(method, path, body=None):
        s_serv, s_client = socket.socketpair()
        server = _PairedServer(s_serv)
        try:
            req = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
            if body is not None:
                req += f"Content-Length: {len(body)}\r\n"
            req += "\r\n"
            s_client.sendall(req.encode())
            if body is not None:
                s_client.sendall(body.encode() if isinstance(body, str) else body)
            s_client.shutdown(socket.SHUT_WR)

            def _runner():
                try:
                    HermesHandler(s_serv, ("in-process", 0), server)
                except Exception:
                    pass
            threading.Thread(target=_runner, daemon=True).start()

            chunks = []
            s_client.settimeout(3)
            while True:
                try:
                    data = s_client.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
                except (socket.timeout, OSError):
                    break
            raw = b"".join(chunks).decode("utf-8", errors="replace")
        finally:
            try:
                s_client.close()
            except Exception:
                pass

        if not raw.startswith("HTTP/"):
            return {"status": 0, "headers": {}, "body": raw}
        head, _, body = raw.partition("\r\n\r\n")
        lines = head.split("\r\n")
        status = int(lines[0].split(" ", 2)[1]) if lines[0].startswith("HTTP/") else 0
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
        return {"status": status, "headers": headers, "body": body}

    failures: list[str] = []

    print("=" * 70)
    print("Bug 1 — current_user 在 GET 响应里")
    print("=" * 70)
    r = http_request("GET", "/api/guidance/implementation")
    if r["status"] != 200:
        failures.append(f"GET status={r['status']} (expected 200): {r['body'][:200]}")
        print(f"  ✗ GET returned {r['status']}: {r['body'][:200]}")
    else:
        payload = json.loads(r["body"])
        print(f"  schema_version: {payload.get('schema_version')}")
        print(f"  current_user:   {payload.get('current_user')!r}")
        print(f"  tasks count:    {len(payload.get('tasks', []))}")
        print(f"  summary:        {payload.get('summary')}")
        if payload.get("current_user") != "alice":
            failures.append(f"current_user mismatch: {payload.get('current_user')!r}")
        else:
            print("  ✓ current_user='alice' as expected")

    print()
    print("=" * 70)
    print("Bug 1 — current_user vs task.by 隔离")
    print("=" * 70)
    r2 = http_request(
        "PATCH",
        "/api/guidance/implementation/1.1_fill_entity_table",
        body=json.dumps({"done": True, "note": "test note by alice"}),
    )
    print(f"  PATCH status: {r2['status']}")
    if r2["status"] != 200:
        failures.append(f"PATCH status={r2['status']}: {r2['body'][:200]}")
    else:
        patch_payload = json.loads(r2["body"])
        task = patch_payload.get("task", {})
        print(f"  task.by: {task.get('by')!r}")
        print(f"  task.done: {task.get('done')}")
        if task.get("by") != "alice":
            failures.append(f"task.by mismatch: {task.get('by')!r}")
        else:
            print("  ✓ task.by='alice' (real completer)")

    r3 = http_request("GET", "/api/guidance/implementation")
    if r3["status"] == 200:
        payload3 = json.loads(r3["body"])
        t11 = next((t for t in payload3["tasks"] if t["id"] == "1.1_fill_entity_table"), None)
        print(f"  GET again → current_user: {payload3.get('current_user')!r}")
        print(f"  GET again → task 1.1 by: {t11.get('by') if t11 else None!r}")
        print(f"  GET again → task 1.1 done: {t11.get('done') if t11 else None}")
        if payload3.get("current_user") != "alice":
            failures.append("current_user changed after PATCH")
        elif not (t11 and t11.get("by") == "alice" and t11.get("done") is True):
            failures.append("task 1.1 state wrong after PATCH")
        else:
            print("  ✓ current_user 持续返回 alice; task.by 持久化为完成时的用户")

    print()
    if failures:
        print("=" * 70)
        print(f"FAILED ({len(failures)})")
        print("=" * 70)
        for f in failures:
            print(f"  - {f}")
        return 1

    print("=" * 70)
    print("All bug 1 end-to-end checks PASSED")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
