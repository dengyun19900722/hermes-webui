# RBAC Workspace 隔离与用户自助改密设计文档

**版本：** v1.0
**日期：** 2026-08-06
**状态：** 待审
**作者：** ZK 运维智能体 + 用户协作产出

---

## 1. 概述

### 1.1 设计目标

本期在已有 RBAC（admin / user 两角色）的基础上扩展两个能力：

1. **Workspace 走 RBAC 策略**：workspaces.json 引入 `owner` / `members` 字段；
   admin 看全部，普通用户只看自己是 owner 或 member 的 workspace。
2. **用户自助修改密码**：右上角菜单新增"修改密码"，强制旧密码、复杂度校验、失效其他会话。
3. **Admin 重置密码**：admin 用户管理面板新增"重置密码"按钮，无需旧密码，可绕过复杂度，强制其他会话登出。
4. **空 workspace 时提醒**：进入会话页（`/chat` 与 `/session/{id}`）若无可见 workspace，
   中央展示 empty state + "+ 创建工作区"快捷入口。创建时若路径不存在，服务器端自动 `mkdir -p`。

### 1.2 范围 / 非范围

**本期包含**：
- 后端：`api/workspace.py` 数据模型迁移 + RBAC 过滤；新增 endpoints；用户改密 + admin 重置 endpoints
- 前端：用户菜单项；admin 用户行重置按钮；chat/session 路由空状态拦截；workspace 列表 owner 标记
- i18n：中英双语新增键
- 迁移：已有 workspaces.json 一次性 in-place 补字段
- 单元测试 + 集成测试

**本期不包含（YAGNI）**：
- workspace 转让 owner
- password_history
- 密码过期策略
- 公开 workspace（self-service join）
- audit log UI 改动（`/api/admin/audit` 已存在即可）

### 1.3 设计原则

- **最小破坏**：workspaces.json 仍是 per-profile（不拆分文件），只加字段
- **后端权威**：RBAC 过滤在后端做，前端不重复实现
- **二次校验**：所有写端点（member add/remove/delete/rename）二次确认操作者是 owner 或 admin
- **不删物理路径**：delete workspace 只从 list 移除，避免误删用户数据
- **迁移幂等**：每次 `load_workspaces()` 都跑迁移，缺字段才补，已存在字段不覆盖

---

## 2. 数据模型与迁移

### 2.1 users.json

保持现状：
```json
{
  "users": [
    {
      "id": "uuid",
      "username": "alice",
      "password_hash": "pbkdf2_sha256$...",
      "role": "user|admin",
      "created_at": "ISO8601",
      "last_login": "ISO8601|null"
    }
  ]
}
```
**不引入** `password_history`、`password_expires_at`、`failed_login_count` 等字段。

### 2.2 workspaces.json（新 schema）

```json
[
  {
    "path": "/abs/path",
    "name": "Display Name",
    "owner": "<user_id>",
    "members": ["<user_id_1>", "<user_id_2>"]
  }
]
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 主键，去重用 |
| `name` | string | 否 | UI 显示名 |
| `owner` | string (user_id) | 是 | 创建者；本期不允许转让 |
| `members` | string[] | 是 | 可见成员；至少包含 owner |

### 2.3 迁移逻辑

`api/workspace.py` 新增 `_migrate_workspace_access(workspaces, state_dir)`，
在 `load_workspaces()` 末尾调用，幂等：

```python
def _migrate_workspace_access(workspaces: list, state_dir: Path) -> list:
    """Idempotent: runs on every load_workspaces() call.
    
    For each workspace missing 'owner' or 'members', backfill with the
    first admin user (by created_at ascending). If no admin exists,
    leave the entry as-is but log a warning + audit event.
    """
    users = load_users(state_dir)
    admins = sorted(
        [u for u in users if u.get("role") == "admin"],
        key=lambda u: u.get("created_at") or "",
    )
    if not admins:
        logger.warning("RBAC workspace migration skipped: no admin user found")
        return workspaces
    first_admin_id = admins[0]["id"]
    needs_persist = False
    for w in workspaces:
        if "owner" not in w or "members" not in w:
            w["owner"] = first_admin_id
            w["members"] = [first_admin_id]
            needs_persist = True
    if needs_persist:
        save_workspaces(workspaces)
        audit_event("workspace.migration", {"owner_default": first_admin_id})
    return workspaces
```

**幂等保证**：只补缺失字段；已有字段不被覆盖。

### 2.4 RBAC 过滤

```python
def visible_workspaces(user_id: str, is_admin: bool, all_ws: list[dict]) -> list[dict]:
    """Filter workspace list by RBAC visibility."""
    if is_admin:
        return all_ws
    return [w for w in all_ws
            if user_id == w.get("owner")
            or user_id in (w.get("members") or [])]
```

在 `load_workspaces()` 内、`_clean_workspace_list()` 之后调用，
返回给上层的是"已过滤"的 list。

### 2.5 操作权限辅助函数

```python
def _require_workspace_op(ws: dict, user: dict, op: str) -> None:
    """Raise 403 if user is neither admin nor owner of workspace."""
    is_admin = user.get("role") == "admin"
    if not is_admin and ws.get("owner") != user["id"]:
        raise HTTPError(403, f"Only owner or admin can {op} workspace")
```

所有写端点（rename/delete/members）第一行调用。

---

## 3. 后端 API

### 3.1 改密 / 重置

#### POST /api/auth/change-password

| 项 | 内容 |
|---|---|
| 鉴权 | 必须登录（任意 role） |
| Body | `{old_password: str, new_password: str}` |
| 校验 | 旧密码 PBKDF2 verify；新密码 ≥ 8 字符 + 同时含字母和数字 |
| 副作用 | 1) `update_password(user_id, hash)` 写 users.json；2) `invalidate_all_user_sessions(user_id, keep_token=current_token)` 删 `.rbac-sessions.json` 中该用户**除当前 token 之外**的所有 token |
| 错误码 | 401 未登录；400 旧密码错 / 新密码不符规则；500 IO |
| 返回 | `{ok: true}` 或 `{error: "..."}` |

#### PUT /api/admin/users/{user_id}/password

| 项 | 内容 |
|---|---|
| 鉴权 | admin only |
| Body | `{new_password: str}` |
| 校验 | 至少非空；**绕过复杂度**（admin reset 的本意就是设新密码） |
| 副作用 | 同上，更新 hash + 失效该用户全部 token |
| 错误码 | 401/403/404/400/500 |

### 3.2 session 失效辅助

`api/auth.py` 已有 `invalidate_user_session`（针对单 token）。
本期新增 `invalidate_all_user_sessions(user_id)`：遍历 `.rbac-sessions.json`，
删所有 `user_id == X` 的 token。

### 3.3 Workspace API

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/workspaces` | 登录 | 列表经 `visible_workspaces(user, is_admin)` 过滤 |
| GET | `/api/workspaces?view=all` | admin | 不过滤；响应加 `view: "all"` |
| POST | `/api/workspaces` | 登录 | body `{path, name?}`；**路径不存在时自动 mkdir -p**；creator 自动成为 owner+members |
| PUT | `/api/workspaces/{path}` | owner or admin | 重命名（body `{name}`） |
| DELETE | `/api/workspaces/{path}` | owner or admin | 从 list 移除（不动磁盘）；**前端必须二次确认 modal**（防误删） |
| POST | `/api/workspaces/{path}/members` | owner or admin | body `{user_id}`；user_id 不存在返回 404 |
| DELETE | `/api/workspaces/{path}/members/{user_id}` | owner or admin | 移人；不允许移除 owner |

> path 在 URL 中需 urlencode，或改用 `?path=` query 参数。

### 3.4 POST /api/workspaces 自动 mkdir 行为

```python
def _add_workspace(self, path: str, name: str | None, user_id: str) -> dict:
    # 1) 走 validate_workspace_to_add 做 fast-fail（block /etc /usr /var 等）
    # 2) 若路径不存在，try mkdir -p
    #    PermissionError → 400
    #    OSError → 400
    # 3) 写 list，creator 自动成为 owner + members[0]
    # 4) audit "workspace.create" {path, name, owner}
    ...
```

错误返回：
- `{error: "Path points to a system directory: <path>"}`（blocked）
- `{error: "无法在 <path> 创建目录：权限不足"}`（PermissionError）
- `{error: "创建目录失败：<reason>"}`（其他 OSError）

成功返回：`{ok: true, created: <bool>, workspace: {...}}`。

### 3.5 审计

所有 admin / owner 操作写 `api/audit.py`：

| action | 触发端点 |
|---|---|
| `password.change` | POST /api/auth/change-password（成功） |
| `password.reset` | PUT /api/admin/users/{id}/password（成功） |
| `workspace.create` | POST /api/workspaces（成功） |
| `workspace.rename` | PUT /api/workspaces/{path}（成功） |
| `workspace.delete` | DELETE /api/workspaces/{path}（成功） |
| `workspace.member.add` | POST /api/workspaces/{path}/members（成功） |
| `workspace.member.remove` | DELETE /api/workspaces/{path}/members/{user_id}（成功） |
| `workspace.migration` | 启动迁移时（仅当 needs_persist） |

audit 类别全部用 `category='rbac'`（与已有 audit 路由一致）。

### 3.6 错误返回惯例

沿用 `rbac_routes.py` 现有风格：`{error: "<human msg>"}` + HTTP 状态码。
中文 message 直接走 i18n 键查找或硬编码中文（与现有 rbac handler 一致）。

---

## 4. 前端 UI

### 4.1 右上角用户菜单

`static/index.html` 的 `#profileDropdown`（行 1996），
菜单底部、"退出登录"上方新增一项：

```
┌──────────────────┐
│ 用户名 (role)    │   已有
├──────────────────┤
│ 修改密码          │   新增（所有登录用户可见）
├──────────────────┤
│ 退出登录          │   已有
└──────────────────┘
```

#### 修改密码模态框

- 字段：旧密码 / 新密码 / 确认新密码（type=password，无 show/hide）
- 客户端校验：长度 ≥ 8 + 同时含字母和数字 + 两次输入一致
- 提交：`api('/api/auth/change-password', {method:'POST', body:{old_password, new_password}})`
- 失败：模态框顶部红字（`password_old_wrong` / `password_too_short` / `password_needs_classes` / `password_mismatch`）
- 成功：toast "密码已更新" + 关闭模态框

复用：login 页样式 + onboarding dialog 骨架。

### 4.2 Admin 用户管理面板

`static/users_panel.js` 用户列表每行操作列加按钮：

```
| 用户名 | role | 最后登录 | 操作 |
                          ├ 重置密码  新增
                          ├ 改 role   已有
                          ├ 改 panels 已有
                          └ 删除      已有
```

点击弹小模态框：
- 字段：新密码（单个）
- 提示："作为管理员重置无需旧密码并强制其他会话登出"
- 提交：`PUT /api/admin/users/{user_id}/password`
- 成功 toast："已重置 <username> 的密码"

### 4.3 会话页 Empty State（无 workspace）

触发位置：`/chat`（`static/boot.js`）和 `/session/{id}`（`static/sessions.js`）的入口。

判定：
```js
const workspaces = await api('/api/workspaces');
if (!workspaces || workspaces.length === 0) {
  renderNoWorkspaceEmptyState();
  return;
}
```

UI（中央 empty state）：

```
        📁
  你还没有可用的工作区
  联系管理员把你加入一个工作区，
  或自己创建一个。

  [+ 创建工作区]
```

"+ 创建工作区"按钮复用现有 workspace 添加对话框（`static/workspace.js`）。
路径输入下方提示："如果路径不存在将自动创建"。

提交：
- 后端返回 `{ok: true, created: true}` → toast "已创建并添加到工作区" + reload
- 后端返回 `{ok: true, created: false}` → toast "已添加到工作区"
- 400 blocked → 模态框顶部红字
- 400 permission → 模态框顶部红字

### 4.4 Workspace 列表 owner/member 标记

`static/workspace.js` 的 workspace 选择器，每项右侧：

- 当前用户是 owner → 显示 `👑 owner`
- 其他成员视图不变
- admin 看 `view=all` 时，列表项右侧显示 `owner: <username>`

### 4.5 i18n 新增键（中英双语）

放 `static/i18n.js` 现有 `password_*` / `workspace_*` 附近：

| 键 | 中文 | English |
|---|---|---|
| `menu_change_password` | 修改密码 | Change password |
| `change_password_title` | 修改密码 | Change password |
| `change_password_old` | 当前密码 | Current password |
| `change_password_new` | 新密码 | New password |
| `change_password_confirm` | 确认新密码 | Confirm new password |
| `change_password_submit` | 提交 | Submit |
| `change_password_cancel` | 取消 | Cancel |
| `password_old_wrong` | 当前密码错误 | Current password is incorrect |
| `password_too_short` | 密码至少 8 个字符 | Password must be at least 8 characters |
| `password_needs_classes` | 密码必须同时包含字母和数字 | Password must contain both letters and digits |
| `password_mismatch` | 两次输入的新密码不一致 | New passwords do not match |
| `password_changed_ok` | 密码已更新 | Password updated |
| `admin_reset_password` | 重置密码 | Reset password |
| `admin_reset_password_title` | 重置 <username> 的密码 | Reset password for <username> |
| `admin_reset_password_hint` | 作为管理员重置无需旧密码并强制其他会话登出 | Admin reset skips old password check and signs out other sessions |
| `admin_reset_password_ok` | 已重置 <username> 的密码 | Password reset for <username> |
| `workspace_empty_title` | 你还没有可用的工作区 | You have no accessible workspaces |
| `workspace_empty_hint` | 联系管理员把你加入一个工作区，或自己创建一个 | Contact your administrator to be added, or create one yourself |
| `workspace_empty_create_btn` | + 创建工作区 | + Create workspace |
| `workspace_role_owner` | 👑 owner | 👑 owner |
| `workspace_owner_label` | owner: <username> | owner: <username> |

### 4.6 组件复用

| 现成组件 | 用于 |
|---|---|
| Workspace 添加对话框（workspace.js） | 创建工作区按钮触发 |
| Profile dropdown（index.html 行 1996） | 菜单项插入点 |
| Toast 工具（static/ui.js） | 成功/失败提示 |
| 现有 admin 用户管理行（users_panel.js） | 加按钮 |

---

## 5. 迁移、测试与验收

### 5.1 迁移细节

- 触发点：`api/workspace.py` 的 `load_workspaces()` 末尾
- 幂等：只补缺失字段，已存在字段不被覆盖
- 失败兜底：无 admin 用户 → 跳过迁移 + warn log + audit（不阻塞启动）
- 性能：迁移只在内存中扫一遍 workspaces.json；冷启动 O(n)，n 远小于 1000
- 手动回滚：从 workspaces.json 移除所有 `owner`/`members` 字段，下次启动会自动重填

### 5.2 测试覆盖

#### 单元测试（pytest，跳过 conftest；走 `python -c`）

| 文件 | 覆盖点 |
|---|---|
| `tests/test_workspace_rbac.py`（新） | `visible_workspaces` 过滤：admin 看全部；普通用户只看到 owner==me 或 members 含 me；迁移幂等；blocked 路径 |
| `tests/test_workspace_auto_create.py`（新） | mkdir -p 行为；blocked 拒绝；OSError 错误返回；重复创建不报错 |
| `tests/test_password_change.py`（新） | `POST /api/auth/change-password` 完整流程：旧密码错 / 短密码 / 不含数字 / 不含字母 / mismatch / 成功；session 失效断言 |
| `tests/test_admin_reset_password.py`（新） | `PUT /api/admin/users/{id}/password`：admin 鉴权 / 普通用户 403 / 不存在 user 404 / 绕过复杂度 / session 失效 |

#### 集成测试（轻量）

| 文件 | 覆盖点 |
|---|---|
| `tests/test_workspace_rbac_integration.py`（新） | 端到端：admin 创建 workspace → 把 user 加入 → user GET 看到；admin DELETE 用户从 workspace → user GET 不再看到 |

#### i18n 测试

- 新增键在中英 locale 各出现一次
- 校验方式（由 writing-plans 阶段决定具体工具）：可以是 grep 脚本校验 i18n.js 中键存在，也可以是 pytest fixture 加载两个 locale 字典对比
- 占位：测试模块 `static/i18n_test` 不存在；writing-plans 阶段需先决定是否新增，或复用现有 i18n 校验模式

### 5.3 验收清单

#### A. 自助改密

- [ ] 用户菜单显示"修改密码"
- [ ] 弹模态框，旧密码错 → 内联红字
- [ ] 新密码 5 位 → "至少 8 个字符"
- [ ] 新密码全字母 → "必须含数字"
- [ ] 两次不一致 → "两次输入不一致"
- [ ] 成功 → toast + 模态框关闭
- [ ] 同一用户其他浏览器/标签登录后被踢出

#### B. Admin 重置

- [ ] admin 面板每行有"重置密码"
- [ ] 弹模态框提示"无需旧密码，会踢其他会话"
- [ ] 普通用户调该端点 → 403
- [ ] 重置后被重置用户被踢出

#### C. Workspace RBAC

- [ ] 登录后 workspace 列表只显示自己有权限的
- [ ] admin 看到全部 + 标记 owner
- [ ] 普通用户创建 workspace → 自动 owner
- [ ] 普通用户进入 `/chat` / `/session/{id}` → 无 workspace 时显示 empty state + 创建按钮
- [ ] 点击创建 → 路径不存在自动 mkdir + 写 list
- [ ] 创建后页面 reload，看到新 workspace
- [ ] owner 拉人 → 被拉用户重新加载后能看到
- [ ] owner 移人 → 被移用户重新加载后看不到
- [ ] owner 重命名 → 列表实时更新
- [ ] owner 删除 → 列表项消失，磁盘路径保留

#### D. 迁移

- [ ] 现有 workspaces.json 中无 owner 字段的条目，迁移后 owner=first_admin
- [ ] 多次启动幂等，不重复写入

#### E. i18n

- [ ] 切到 en locale，所有新文案显示英文
- [ ] 切回 zh-CN 显示中文

### 5.4 风险与缓解

| 风险 | 缓解 |
|---|---|
| 迁移脚本误覆盖已设置的 owner | 幂等：只补缺失字段 |
| mkdir 在受控目录外意外创建 | `_is_blocked_workspace_path` + `_trusted_workspace_roots` 双重检查 |
| session 失效导致用户当前页面 401 | 模态框文案："其他设备将立即登出"；当前 session 保留 |
| admin 误删 workspace | 删除端点对 admin 也要求走 DELETE + 二次确认 modal |
| profile 内跨 user 误共享 owner | 强制 owner 字段必填，迁移保证 |

---

## 6. 实施计划（待 writing-plans 展开）

预期任务拆分：

1. **后端骨架**：`api/user_store.py` 增加 `update_password`；`api/auth.py` 增加 `invalidate_all_user_sessions`
2. **改密 endpoints**：新增 `POST /api/auth/change-password` + `PUT /api/admin/users/{id}/password`
3. **Workspace RBAC**：`api/workspace.py` 增加 `visible_workspaces` / `_require_workspace_op` / `_migrate_workspace_access`
4. **Workspace API**：补齐 owner-or-admin gated endpoints（rename/delete/member add/remove）
5. **POST 自动 mkdir**：在 `_add_workspace` 内嵌 mkdir -p 逻辑
6. **i18n**：补 `static/i18n.js` 中英 22 条键
7. **前端菜单**：用户菜单加"修改密码"项 + 模态框
8. **前端 admin 重置**：`users_panel.js` 加按钮 + 模态框
9. **前端空状态**：chat/session 路由加 empty state + 创建按钮
10. **前端 owner 标记**：workspace 列表 owner 显示
11. **测试**：上述 4 个新单测 + 1 个集成测试
12. **验收**：5 项清单逐一过

---

## 7. 决策记录

- **不引入 ops 角色**：用户未要求；admin/user 二元结构保持
- **不转让 owner**：用户选择"加/减成员 / 删除 / 重命名"三项，未选"转让"
- **admin 看全部 vs view=all 参数**：用 query 参数区分（与现有过滤一致），不引入新资源路径
- **i18n 中英双语**：用户选择双语，避免后续补键
- **path 走 urlencode 还是 query 参数**：建议 query 参数（避免路径含 `/` 时的解码复杂度），由 writing-plans 阶段确定
- **删除 workspace 不删磁盘**：避免误删用户数据；user 后续可重新添加
