# 2026-08-13 RBAC 菜单权限未生效与 Settings 卡死故障修复

## 1. 背景

线上反馈：

- admin 在 Settings 里修改其它用户的菜单权限后，切换到目标账号发现菜单权限未生效。
- Settings 页面配置用户菜单权限时，页面可能卡死或保存后无明显反馈。
- 多账号切换场景下担心旧账号菜单、workspace、session 等前端缓存残留。

本次修复聚焦 RBAC 菜单权限的端到端一致性：

1. admin 保存用户菜单权限必须写入用户记录。
2. `/api/auth/status` 必须返回当前登录用户的真实菜单权限。
3. 退出登录和账号切换时必须清理前端身份快照、role、panels 和 auth/status 短缓存。
4. Settings 保存权限后页面不能卡死，modal 应关闭，按钮应恢复，页面应继续可操作。

安全约束：本文不记录生产账号密码、Cookie、token、完整 `.env`、完整 `auth.json` 或可复用的私有访问地址。

## 2. 影响范围

影响用户：

- 使用 RBAC 多用户模式的部署。
- admin 通过 Settings -> Users 修改其它用户菜单权限的场景。
- admin 退出后登录普通用户，或普通用户之间切换的场景。

可见症状：

- admin 把某用户菜单权限清空或缩小后，目标用户登录仍看到默认菜单。
- 目标用户不应看到 Settings，却仍看到 Settings。
- 退出登录后 localStorage 中仍残留 `hermes-webui-auth-role=admin`。
- Settings 保存权限后弹窗不关闭，按钮一直处于保存中，或页面不响应点击。

## 3. 根因

### 3.1 显式空菜单被当成默认值

后端 `/api/auth/status` 原逻辑等价于：

```python
"panels": rbac_user.get("panels") or list(DEFAULT_USER_PANELS)
```

这会把 `panels: []` 当成 falsy 值，并回落到 `DEFAULT_USER_PANELS`。

结果是：admin 明确保存“无可访问菜单”后，目标用户登录时仍拿到默认菜单，例如 `["chat", "tasks", "skills", "knowledge"]`。

正确语义：

- `panels` 字段不存在或不是数组：旧数据兼容，回落默认菜单。
- `panels` 字段存在且是空数组：这是 admin 的显式授权结果，必须保留空数组。

### 3.2 退出登录没有完整清理前端身份快照

前端退出登录原先主要清理：

- `hermes-webui-auth-user-id`
- `hermes-webui-session`

但没有完整清理：

- `hermes-webui-auth-role`
- `window._currentAuthRole`
- `window._currentUserPanels`
- `/api/auth/status` 短 TTL snapshot
- 正在等待的 auth/status promise generation

这会造成新账号首屏短时间沿用旧账号 role/panels。尤其从 admin 切普通用户时，旧 `admin` role 可能让菜单先按 admin 显示。

### 3.3 Settings 初始化异常会放大“卡死”体验

Settings 页面初始化逻辑较长，任何同步 JavaScript 异常都可能中断后续绑定。历史问题里曾出现部分 WebView 或旧浏览器暴露 `speechSynthesis`，但不提供 `speechSynthesis.addEventListener`，直接调用会抛出异常，使 Settings 后续初始化中断。

本次验证中，保存菜单权限路径已确认不再卡死：

- 保存按钮会恢复。
- modal 会关闭。
- 页面 event loop 正常。
- 可继续切换 Chat / Settings。

## 4. 修复内容

### 4.1 后端保留显式空 panels

文件：`api/routes.py`

修复点：

```python
panels = rbac_user.get("panels")
if not isinstance(panels, list):
    panels = list(DEFAULT_USER_PANELS)
```

效果：

- `panels: []` 返回 `[]`。
- 旧用户缺少 `panels` 字段时仍返回默认菜单，兼容旧数据。

### 4.2 前端新增统一身份快照清理

文件：`static/boot.js`

新增 `clearAuthIdentityScopeRuntime()`：

- 增加 auth status generation，废弃旧在途请求。
- 清空 `_authIdentityStatusPromise`。
- 清空 `_authIdentityStatusSnapshot`。
- 清空 `window._currentAuthUserId`。
- 清空 `window._currentAuthRole`。
- 清空 `window._currentUserPanels`。
- 删除 localStorage 中的 auth user id 和 auth role。
- 重新应用 tab visibility。

### 4.3 退出登录调用统一清理

文件：`static/panels.js`

`signOut()` 在 `/api/auth/logout` 成功后调用 `window.clearAuthIdentityScopeRuntime()`，fallback 分支也显式清理 role 和 panels。

效果：

- 从 admin 退出后，普通用户登录不再继承 admin 菜单。
- BFCache 或短时间连续切换账号时，旧 auth/status snapshot 不再污染新账号。

### 4.4 当前账号被修改时刷新身份状态

文件：`static/users_panel.js`

保存菜单权限或切换角色后，如果被修改的是当前登录用户：

- 强制调用 `syncAuthIdentityScope({ force: true, clearOnChange: false })`。
- 重新应用 tab visibility。
- 从缓存重新渲染 session list。

这保证 admin 修改自己的菜单或角色时当前页立即体现最新身份状态。admin 修改其它用户时，该用户下次登录通过 `/api/auth/status` 获取最新 panels。

### 4.5 Settings 初始化防御

文件：`static/panels.js`

对 `speechSynthesis.addEventListener` 增加 `typeof === 'function'` 判断，避免浏览器兼容性异常中断 Settings 初始化。

## 5. 验证结果

### 5.1 自动化测试

已通过：

```bash
./scripts/test.sh \
  tests/test_routes_rbac.py::test_auth_status_preserves_explicit_empty_user_panels \
  tests/test_routes_rbac.py::test_auth_status_defaults_only_when_user_panels_missing \
  tests/test_session_share_ui.py::test_sign_out_clears_auth_role_panels_and_status_snapshot \
  tests/test_session_share_ui.py::test_session_sidebar_cache_is_scoped_by_authenticated_user \
  tests/test_users_panel_ui.py
```

结果：

- `23 passed`

语法检查：

```bash
node --check static/boot.js
node --check static/panels.js
node --check static/users_panel.js
```

结果：全部通过。

扩展相关测试：

```bash
./scripts/test.sh \
  tests/test_routes_rbac.py \
  tests/test_auth_login.py \
  tests/test_admin_users.py \
  tests/test_session_share_ui.py \
  tests/test_sidebar_tab_visibility.py \
  tests/test_workspace_auth_scope_ui.py
```

结果：

- `89 passed`
- `1 failed`

已知无关失败：

- `tests/test_session_share_ui.py::test_license_machine_identity_runtime_fallback_exists`
- 原因：当前 checkout 缺少 `sitecustomize.py`，单独运行该测试也失败。
- 该失败与本次 RBAC 菜单权限修复无关。

### 5.2 浏览器端验证

使用隔离状态启动临时 WebUI，创建：

- `admin`，role 为 admin。
- `target`，role 为 user，初始 panels 为 `["chat", "skills"]`。

验证 1：admin 通过接口保存 target panels 为 `[]`，退出后登录 target。

结果：

```json
{
  "targetStatusUser": "target",
  "targetStatusPanels": [],
  "runtimeRole": "user",
  "runtimePanels": [],
  "localRole": "user",
  "visiblePanels": ["chat"],
  "hiddenPanels": [
    "insights",
    "kanban",
    "knowledge",
    "logs",
    "memory",
    "profiles",
    "settings",
    "skills",
    "tasks",
    "todos",
    "workspaces"
  ]
}
```

验证 2：Settings -> Users -> target -> 面板权限 modal 中保存为空数组。

结果：

```json
{
  "ok": true,
  "saveMs": 105,
  "modalClosed": true,
  "saveBtnDisabled": false,
  "eventLoopDelayMs": 152,
  "stillInteractive": true,
  "afterSwitchInteractive": true,
  "toggledPanel": "chat",
  "errors": [],
  "targetPanels": []
}
```

判断：

- 保存耗时正常。
- modal 正常关闭。
- 保存按钮恢复可用。
- event loop 150ms 探针正常返回。
- 保存后页面仍可切换 Chat。
- 没有捕获到 JS error 或 unhandled rejection。

## 6. 线上人工日志排查步骤

本节用于值班人员在生产环境人工排查类似问题。排查目标是回答四个问题：

1. admin 的保存请求是否到达后端。
2. 保存请求是否成功并写入 audit。
3. 目标用户登录后 `/api/auth/status` 是否返回正确 panels。
4. 前端是否仍带旧账号 role/panels 或 Settings 初始化异常。

### 6.1 安全准备

不要在聊天、工单或群里粘贴以下内容：

- `Cookie` 请求头。
- `Authorization` 请求头。
- 登录密码。
- 完整 `.env`。
- 完整 `auth.json`。
- API key、OAuth token、refresh token。
- 可直接复用的公网访问地址和临时登录链接。

可以记录：

- 时间窗口。
- HTTP 方法、路径、状态码、耗时。
- 用户名或脱敏后的用户 id。
- audit 中的 action、target、old/new panels。
- 浏览器 console 的错误类型和堆栈文件名。

### 6.2 确认服务和时间窗口

先确认问题发生的绝对时间，尽量使用 UTC 和本地时间各记一次。

```bash
date
date -u
./ctl.sh status
```

记录：

- WebUI 端口。
- WebUI 启动时间。
- 用户操作发生时间，例如 `2026-08-13 09:50:00 CST`。
- admin 修改的是哪个目标用户。
- 预期 panels，例如 `[]` 或 `["chat", "skills"]`。

### 6.3 查看 WebUI 请求日志

默认 daemon 日志：

```bash
./ctl.sh logs --lines 500
```

如果直接看文件，常见路径：

```bash
tail -n 500 ~/.hermes/webui.log
```

按关键接口过滤：

```bash
./ctl.sh logs --lines 3000 \
  | rg '(/api/auth/login|/api/auth/logout|/api/auth/status|/api/admin/users|/panels|/api/settings|\\[webui\\] ERROR|Client event)'
```

重点看这些请求：

| 请求 | 正常状态 | 说明 |
|---|---:|---|
| `POST /api/auth/login` | 200 | admin 或目标用户登录成功 |
| `PUT /api/admin/users/<id>/panels` | 200 | admin 保存用户菜单权限成功 |
| `GET /api/auth/status` | 200 | 前端读取当前登录身份和 panels |
| `POST /api/auth/logout` | 200 | 退出登录成功 |
| `GET /api/admin/users` | 200 | admin 用户列表刷新成功 |

异常判断：

- `PUT /api/admin/users/<id>/panels` 是 401：admin 会话失效或 Cookie 未带上。
- `PUT /api/admin/users/<id>/panels` 是 403：当前用户不是 admin。
- `PUT /api/admin/users/<id>/panels` 是 400：请求 body 中 `panels` 不是数组。
- `PUT /api/admin/users/<id>/panels` 是 404：目标用户 id 不存在。
- 出现 `[webui] ERROR ... /api/admin/users/.../panels`：看紧随其后的 Python traceback。
- 点击保存后日志里没有 PUT 请求：前端事件绑定或 Settings 初始化可能已中断。

请求日志样式示例：

```text
[webui] {"ts":"2026-08-13T01:42:44Z","method":"PUT","path":"/api/admin/users/<user-id>/panels","status":200,"ms":1.6}
```

### 6.4 查看 RBAC 审计日志

审计日志默认目录：

```bash
echo "${HERMES_WEBUI_AUDIT_DIR:-${HERMES_WEBUI_STATE_DIR:-$HOME/.hermes/webui}/audit-logs}"
```

默认文件名：

```bash
audit-YYYY-MM-DD.jsonl
```

查当天 RBAC 相关事件：

```bash
AUDIT_DIR="${HERMES_WEBUI_AUDIT_DIR:-${HERMES_WEBUI_STATE_DIR:-$HOME/.hermes/webui}/audit-logs}"
AUDIT_FILE="$AUDIT_DIR/audit-$(date -u +%F).jsonl"

jq -r '
  select(.category == "rbac")
  | select(.action == "auth.login" or .action == "auth.logout" or .action == "user.panels_change")
  | [.ts, .actor_name, .action, .target_name, (.details | tostring)]
  | @tsv
' "$AUDIT_FILE"
```

如果刚操作完没有看到 audit，先等 5 秒再查。audit 是异步缓冲写入，进程正常退出时也会 flush。

重点看 `user.panels_change`：

```json
{
  "category": "rbac",
  "action": "user.panels_change",
  "actor_name": "admin",
  "target_name": "target",
  "details": {
    "old_panels": ["chat", "skills"],
    "new_panels": []
  }
}
```

判断：

- audit 中没有 `user.panels_change`：保存请求没有成功进入业务逻辑，回到请求日志查 PUT 状态码。
- audit 中 `new_panels` 不是预期值：前端提交值不对，检查 modal checkbox 状态和请求 body。
- audit 中 `new_panels` 正确，但目标用户登录后仍看旧菜单：继续查 `/api/auth/status` 和前端缓存。

### 6.5 检查 users.json 落盘状态

在服务器上确认目标用户记录：

```bash
STATE_DIR="${HERMES_WEBUI_STATE_DIR:-$HOME/.hermes/webui}"

jq '.users[] | select(.username == "target") | {id, username, role, panels}' \
  "$STATE_DIR/users.json"
```

把 `target` 换成真实目标用户名。

正常结果示例：

```json
{
  "id": "<user-id>",
  "username": "target",
  "role": "user",
  "panels": []
}
```

判断：

- `users.json` 中 panels 正确，但页面不正确：问题在 auth/status 或前端缓存。
- `users.json` 中 panels 不正确：问题在保存请求或后端更新用户记录。
- `users.json` 中没有 panels 字段：旧数据兼容会走默认菜单，需要 admin 明确保存一次。

### 6.6 在浏览器验证 auth/status

用目标用户登录后，打开 DevTools Console，执行：

```js
await fetch('/api/auth/status', {
  credentials: 'include',
  cache: 'no-store'
}).then(r => r.json())
```

正常结果应包含：

```json
{
  "logged_in": true,
  "user": {
    "username": "target",
    "role": "user",
    "panels": []
  }
}
```

判断：

- `user.panels` 是默认菜单，但 `users.json` 是 `[]`：后端版本未包含本次修复，或服务未重启到新代码。
- `user.panels` 是 `[]`，但页面仍显示其它菜单：前端 bundle 或运行态缓存有问题。
- `role` 仍是 `admin`：登录态或 Cookie 指向的不是目标用户。

### 6.7 在浏览器验证前端缓存和菜单 DOM

目标用户登录后，在 DevTools Console 执行：

```js
({
  roleStorage: localStorage.getItem('hermes-webui-auth-role'),
  authUserStorage: localStorage.getItem('hermes-webui-auth-user-id'),
  runtimeUser: window._currentAuthUserId,
  runtimeRole: window._currentAuthRole,
  runtimePanels: window._currentUserPanels
})
```

再检查菜单可见性：

```js
[...document.querySelectorAll('.nav-tab[data-panel], .rail-btn.nav-tab[data-panel]')]
  .map(el => ({
    panel: el.dataset.panel,
    hidden: el.classList.contains('nav-tab-hidden'),
    display: getComputedStyle(el).display
  }))
```

目标用户 panels 为 `[]` 时，预期：

- `runtimeRole` 为 `"user"`。
- `runtimePanels` 为 `[]`。
- `roleStorage` 为 `"user"`。
- `chat` 可见。
- `settings` 隐藏。
- `tasks/skills/knowledge/workspaces` 等非授权菜单隐藏。

如果 `roleStorage` 仍是 `admin`，说明退出登录清理或新 bundle 生效有问题。

### 6.8 排查 Settings 卡死

当用户报告 Settings 里保存菜单权限后卡死，按以下顺序查：

1. 看请求日志中是否出现 PUT：

```bash
./ctl.sh logs --lines 2000 | rg '/api/admin/users/.*/panels'
```

2. 如果没有 PUT，请查浏览器 Console：

```text
TypeError
ReferenceError
speechSynthesis.addEventListener is not a function
savePanelsEditor
loadSettingsPanel
users_panel.js
panels.js
```

3. 如果有 PUT 且 200，但 modal 不关闭，查 Console 是否有保存后的异常：

```text
loadUsers
loadAudit
syncAuthIdentityScope
_applyTabVisibility
renderSessionListFromCache
```

4. 如果 PUT 长时间 pending，查服务端是否有慢请求或锁：

```bash
./ctl.sh logs --lines 3000 | rg '(/api/admin/users|/api/auth/status|status.:500|\\[webui\\] ERROR|ms.:([5-9][0-9]{3,}|[0-9]{5,}))'
```

5. 在浏览器 Console 做 event loop 探针：

```js
const t = performance.now();
await new Promise(resolve => setTimeout(resolve, 150));
Math.round(performance.now() - t);
```

正常应接近 150ms 到 300ms。如果明显超过数秒，说明页面主线程被同步任务阻塞，需要采集 Performance 录制和 Console 错误。

### 6.9 判断矩阵

| 现象 | 日志证据 | 可能原因 | 处理 |
|---|---|---|---|
| 点击保存无网络请求 | 无 `PUT /api/admin/users/.../panels` | Settings JS 初始化或按钮事件异常 | 查浏览器 Console，重点看 `TypeError/ReferenceError` |
| PUT 401 | 请求日志 status 401 | admin 会话失效 | 重新登录 admin，确认 Cookie 未被代理剥离 |
| PUT 403 | 请求日志 status 403 | 当前账号不是 admin | 用 `/api/auth/status` 确认 role |
| PUT 200 但 audit 无变更 | audit 延迟或写入异常 | audit 异步缓冲或 AUDIT_DIR 问题 | 等 5 秒复查，确认 `HERMES_WEBUI_AUDIT_DIR` |
| audit `new_panels: []`，目标用户仍看到默认菜单 | `/api/auth/status.user.panels` 返回默认菜单 | 后端未部署本修复或服务未重启 | 确认代码和进程版本，重启 WebUI |
| auth/status 返回 `[]`，页面仍显示旧菜单 | `window._currentAuthRole` 或 localStorage 仍是 admin | 前端旧 bundle 或退出清理未生效 | 硬刷新、清 SW/cache，确认 `clearAuthIdentityScopeRuntime` 在 bundle 中 |
| 退出后登录目标用户仍显示 admin 菜单 | localStorage `hermes-webui-auth-role=admin` | 退出未清 role | 确认 `static/panels.js` 和 `static/boot.js` 是新版本 |
| Settings 保存后卡住 | Console 有 `speechSynthesis.addEventListener` 异常 | 浏览器兼容性问题中断 Settings 初始化 | 确认 speechSynthesis guard 已部署 |
| Settings 保存慢 | 请求日志 ms 很高 | 后端 IO 或锁等待 | 查同时间窗口 `[webui] ERROR`、系统负载、磁盘 IO |

### 6.10 确认线上代码是否包含修复

在部署目录执行：

```bash
rg -n 'panels = rbac_user.get\\("panels"\\)|clearAuthIdentityScopeRuntime|speechSynthesis.addEventListener' \
  api/routes.py static/boot.js static/panels.js
```

应看到：

- `api/routes.py` 中先读取 `panels = rbac_user.get("panels")`，再判断 `not isinstance(panels, list)`。
- `static/boot.js` 中存在 `clearAuthIdentityScopeRuntime()`。
- `static/panels.js` 中 `signOut()` 调用 `window.clearAuthIdentityScopeRuntime()`。
- `static/panels.js` 中调用 `speechSynthesis.addEventListener` 前有 `typeof speechSynthesis.addEventListener === 'function'`。

如果源码正确但浏览器仍旧行为：

- 检查页面加载的 `static/boot.js?v=...` 和 `static/panels.js?v=...` 是否为新版本。
- 尝试硬刷新。
- 如果启用 service worker，DevTools -> Application -> Service Workers 中 unregister 后再刷新。
- 确认 WebUI 进程已经重启，不是旧进程仍在端口上。

## 7. 线上修复后验收清单

修复部署后，至少完成以下验收：

1. admin 登录，打开 Settings -> Users。
2. 修改一个普通用户 panels 为 `[]`，保存。
3. 确认请求日志有 `PUT /api/admin/users/<id>/panels` 且 status 200。
4. 确认 audit 有 `user.panels_change` 且 `new_panels` 为 `[]`。
5. admin 退出登录。
6. 确认浏览器 localStorage 不再有 `hermes-webui-auth-role=admin`。
7. 登录目标用户。
8. DevTools Console 执行 `/api/auth/status`，确认 `user.panels` 为 `[]`。
9. 确认页面只显示 Chat，Settings 和其它未授权菜单隐藏。
10. 再切回 admin，把目标用户 panels 恢复为业务预期值。
11. 重复验证目标用户登录后的菜单符合恢复后的授权。

## 8. 回滚和风险

本次修复是低风险语义修复：

- 后端只改变 `panels: []` 的返回语义，保留旧数据缺字段时默认菜单兼容。
- 前端清理只发生在退出登录或身份清理路径，不影响正常登录态。
- Settings 保存后强制刷新当前身份只影响当前用户被修改的场景。

不建议回滚到旧逻辑，因为旧逻辑会再次把显式空菜单恢复成默认菜单。

如必须紧急回滚，应同步采取临时缓解：

- 不要给用户保存 `panels: []`，至少保留 `["chat"]`。
- 要求用户退出后清浏览器缓存或使用无痕窗口重新登录。
- admin 修改权限后，用 `/api/auth/status` 手工确认目标用户实际返回值。

## 9. 后续建议

- 增加一条端到端浏览器测试：admin 在 Settings UI 保存 target panels 为 `[]`，退出后登录 target，断言只显示 Chat。
- 给 `/api/auth/status` 响应增加更明确的测试夹具，覆盖 `panels=[]`、`panels` 缺失、`panels=null` 三类。
- 在 UI 中给 admin 展示“保存成功并已写入”的轻量 toast，减少用户重复点击。
- 在 Settings Users 面板增加当前目标用户 panels 的只读摘要，便于人工排查截图留证。
