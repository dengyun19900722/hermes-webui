# RBAC 权限体系设计文档

**版本：** v1.0
**日期：** 2026-07-08
**状态：** 已批准

---

## 1. 概述

### 1.1 设计目标

- 实现多用户认证与会话隔离
- 支持会话在用户间可选分享
- 知识库系统级共享，文档标记创建者，支持用户评价
- 管理员可查看所有会话和用户管理
- 基于本地文件存储，无数据库依赖

### 1.2 部署模式

**单租户模式**：所有用户共享一个 Hermes 实例，用户 A 的会话/知识除非明确共享，否则完全私密。

### 1.3 设计原则

- **会话隔离默认私有**：用户只能看到自己的会话
- **知识库系统级共享**：所有用户访问同一知识库，文档标记创建者
- **管理员可查看所有会话**：用于系统管理和审计
- **License 优先**：License 校验作为平台级入口前置条件，必须先于 RBAC 登录
- **轻量实现**：最小化数据库改动，与现有文件结构兼容

### 1.4 License 兼容性

RBAC 系统与现有 License 模块**强耦合**：
- License 未激活 → 重定向到 `/license/activate`（RBAC 流程不可见）
- License 已激活但未初始化 RBAC → 进入 RBAC 首次部署流程
- License 已激活且 RBAC 已初始化 → 进入 RBAC 登录页
- License 已过期 / `copied` → 拒绝所有访问

**License 状态转换流程：**

```
[未激活] ──激活──> [已激活+未初始化RBAC] ──创建admin──> [已激活+已初始化]
                                                                     │
                                                                     ▼
                                                              [RBAC登录页]
                                                                     │
                                                                     ▼
                                                              [登录成功]
```

**License 异常状态：**

| 状态 | 行为 |
|------|------|
| `not_activated` | 全部请求重定向到 `/license/activate`（除 `/health`、`/api/license/*`、`/static/*`） |
| `expired` | 全部请求 403，显示"License 已过期" |
| `copied` | 全部请求 403，显示"License 检测到 MAC 变更" |
| `valid` + RBAC 未初始化 | 重定向到 `/setup`（首次部署） |
| `valid` + RBAC 已初始化 | 显示登录页或应用主页 |

---

## 2. 存储结构

所有数据存储在 `$STATE_DIR/` 目录下：

```
$STATE_DIR/
├── users.json              # 用户列表
├── sessions/               # 会话目录
│   └── {user_id}/
│       ├── sessions.json   # 该用户的所有会话
│       └── shares.json     # 该用户的分享记录（outgoing/incoming）
├── knowledge/              # 知识库（Obsidian vault）
│   ├── {category}/         # 如 01-故障知识库/
│   │   └── *.md            # Markdown 文档
│   └── .meta/              # 元数据目录
│       └── {category}/{doc_name}.meta.json  # 文档元数据
└── audit.json              # 管理员审计日志

**注意：** 会话文件存储在会话所有者目录下，被分享的会话通过 `shares.json` 引用访问，无需复制。
```

---

## 3. 数据模型

### 3.1 用户表 (users.json)

```json
{
  "users": [
    {
      "id": "uuid",
      "username": "用户名",
      "password_hash": "pbkdf2_sha256_xxx",
      "role": "user|admin",
      "created_at": "ISO8601",
      "last_login": "ISO8601"
    }
  ]
}
```

### 3.2 会话表 (sessions/{user_id}/sessions.json)

```json
{
  "sessions": [
    {
      "id": "uuid",
      "title": "会话标题",
      "owner_id": "user_uuid",
      "created_at": "ISO8601",
      "updated_at": "ISO8601",
      "share_token": "random_token_xxx|null"
    }
  ]
}
```

### 3.3 分享记录表 (sessions/{user_id}/shares.json)

```json
{
  "outgoing": [
    {
      "id": "uuid",
      "to_user_id": "target_user_uuid|null",
      "session_id": "session_uuid",
      "type": "user|token",
      "token": "share_token|null",
      "created_at": "ISO8601",
      "expires_at": "ISO8601|null"
    }
  ],
  "incoming": [
    {
      "id": "uuid",
      "from_user_id": "source_user_uuid",
      "session_id": "session_uuid",
      "type": "user|token",
      "created_at": "ISO8601"
    }
  ]
}
```

### 3.4 知识库元数据 (knowledge/.meta/{category}/{doc_name}.meta.json)

```json
{
  "creator_id": "user_uuid",
  "creator_name": "用户名",
  "created_at": "ISO8601",
  "ratings": [
    {"user_id": "xxx", "username": "xxx", "rating": 1-5, "created_at": "ISO8601"}
  ]
}
```

### 3.5 审计日志 (audit.json)

```json
{
  "logs": [
    {
      "id": "uuid",
      "timestamp": "ISO8601",
      "actor_id": "user_uuid",
      "actor_name": "用户名",
      "action": "session.share|user.create|doc.delete|...",
      "target_type": "session|user|doc|...",
      "target_id": "target_uuid",
      "target_name": "目标名称",
      "ip_address": "x.x.x.x",
      "details": {}
    }
  ]
}
```

---

## 4. 会话隔离与分享

### 4.1 会话隔离规则

| 角色 | 可见范围 |
|------|----------|
| 普通用户 | 只能看到自己的会话 + 被分享的会话 |
| 管理员 (admin) | 可见所有用户的会话 |

### 4.2 分享机制

**方式一：用户间直接分享**
- 用户 A 选择会话，分享给用户 B
- 在 `sessions/{A}/shares.json` 的 `outgoing` 添加记录
- 在 `sessions/{B}/shares.json` 的 `incoming` 添加记录

**方式二：Token 链接分享**
- 用户 A 开启会话的 `share_token`
- 生成链接：`/shared/session?token=xxx`
- 任何人通过 token 均可查看该会话

### 4.3 分享的会话呈现

- 显示在独立的**"收到的分享"**分区
- 标记来源用户（如"来自 张三的分享"）
- **只读**显示，不能修改或删除原会话

---

## 5. 知识库扩展

### 5.1 现有实现

已有 `obsidian_notes.py` 模块管理 Obsidian vault：
- Markdown 文件存储在 `$HERMES_OBSIDIAN_VAULT_DIR` 目录
- 默认路径：`{DEFAULT_WORKSPACE}/obsidian/`
- 分类目录：如 `01-故障知识库/`、`02-运维手册/`、`03-FAQ/`

### 5.2 元数据扩展

为支持**创建者标记**和**用户评价**，新增 `.meta.json` 侧写文件。

### 5.3 知识库访问规则

| 操作 | 权限 |
|------|------|
| 查看/搜索文档 | 所有登录用户 |
| 创建文档 | 所有登录用户 |
| 编辑文档 | 仅文档创建者 |
| 删除文档 | 仅文档创建者或 admin |
| 评价文档 | 所有登录用户（每人只能评价一次，可修改） |

---

## 6. 用户认证与会话管理

### 6.1 认证流程

| 步骤 | 说明 |
|------|------|
| 1. 首次部署 | 用户设置初始管理员账号（username + password） |
| 2. 登录 | username + password → 验证 → 创建 auth session cookie |
| 3. 后续用户 | 由 admin 在管理面板创建，或开放注册 |
| 4. 会话保持 | 30 天过期，活跃用户自动续期 |

### 6.2 密码管理

- PBKDF2-SHA256 + 600k 迭代（OWASP 标准）
- 密码 hash 存储在 `users.json` 中
- 首次部署检测到 `users.json` 为空，强制进入初始化流程

### 6.3 管理员权限

| 权限 | 说明 |
|------|------|
| 查看所有用户会话 | 可在管理面板查看任意用户的会话 |
| 管理用户 | 创建/删除/禁用用户，修改用户角色 |
| 管理知识库 | 删除任意文档 |
| 系统配置 | 修改系统级设置 |

---

## 7. 管理员面板与审计

### 7.1 管理员面板

新增 `/admin` 路由，供 admin 角色访问：

| 功能 | 说明 |
|------|------|
| 用户管理 | 查看/创建/编辑/删除用户，分配角色 |
| 会话审计 | 查看所有用户的会话列表（只读，不可操作） |
| 知识库管理 | 删除任意文档 |
| 系统信息 | 查看在线用户、存储使用情况 |

### 7.2 审计事件类型

| 事件 | 说明 |
|------|------|
| `session.share` | 用户分享会话 |
| `session.share_accept` | 用户接收分享 |
| `user.create` | 管理员创建用户 |
| `user.delete` | 管理员删除用户 |
| `user.role_change` | 管理员修改用户角色 |
| `doc.create` | 用户创建文档 |
| `doc.delete` | 用户/管理员删除文档 |
| `doc.rate` | 用户评价文档 |
| `auth.login` | 用户登录 |
| `auth.logout` | 用户登出 |

### 7.3 审计日志保留

- 默认保留 30 天
- 可配置保留期限（管理员设置）
- 超过保留期的日志自动清理

---

## 8. API 路由设计

### 8.1 用户认证 API

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/auth/register` | 首次部署初始化管理员 | 无（首次部署） |
| POST | `/api/auth/login` | 用户登录 | 无 |
| POST | `/api/auth/logout` | 用户登出 | 登录用户 |
| GET | `/api/auth/status` | 获取当前用户状态 | 登录用户 |

### 8.2 用户管理 API（管理员）

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/admin/users` | 获取用户列表 | admin |
| POST | `/api/admin/users` | 创建用户 | admin |
| PUT | `/api/admin/users/{id}` | 更新用户 | admin |
| DELETE | `/api/admin/users/{id}` | 删除用户 | admin |

### 8.3 会话分享 API

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/sessions` | 获取当前用户的会话列表 | 登录用户 |
| GET | `/api/sessions/shared` | 获取收到的分享会话 | 登录用户 |
| POST | `/api/sessions/{id}/share` | 分享会话给指定用户 | 会话所有者 |
| POST | `/api/sessions/{id}/share/token` | 生成分享链接 token | 会话所有者 |
| DELETE | `/api/sessions/{id}/share/{share_id}` | 取消分享 | 会话所有者 |
| GET | `/api/shared/session?token=xxx` | 通过 token 访问分享的会话 | 持有有效 token |

### 8.4 知识库元数据 API

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/notes/meta/{path}` | 获取文档元数据 | 登录用户 |
| POST | `/api/notes/meta/{path}/rate` | 评价文档 | 登录用户 |
| GET | `/api/notes/meta/{path}/ratings` | 获取文档评价列表 | 登录用户 |

### 8.5 管理员 API

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/admin/sessions` | 查看所有用户会话 | admin |
| GET | `/api/admin/audit` | 获取审计日志 | admin |
| GET | `/api/admin/stats` | 系统统计信息 | admin |

---

## 9. 实现计划

### Phase 0: License 与 RBAC 集成（前置）
1. 在 `routes.py` 中间件层添加 License 状态检查
2. License 未激活时拦截除 `/license/*`、`/health`、`/static/*` 之外的请求
3. License 已激活但 RBAC 未初始化时重定向到 `/setup`
4. License 状态异常（expired/copied）返回 403
5. 复用现有 `api/license.py` 模块，**不修改** License 业务逻辑

### Phase 1: 用户认证系统
1. 扩展 `api/auth.py`，支持多用户
2. 实现 `users.json` 读写
3. 实现用户注册、登录、登出
4. 首次部署初始化流程

### Phase 2: 会话隔离与分享
1. 修改会话存储结构，支持多用户
2. 实现会话隔离查询
3. 实现用户间分享机制
4. 实现 Token 链接分享

### Phase 3: 知识库元数据
1. 实现 `.meta.json` 侧写文件机制
2. 扩展文档创建/编辑/删除时更新元数据
3. 实现用户评价功能
4. 更新文档列表 API，附加评价统计

### Phase 4: 管理员面板
1. 实现 `/admin` 路由
2. 实现用户管理 CRUD
3. 实现审计日志记录
4. 实现审计日志查询

---

## 10. License 中间件检查

### 10.1 检查时机

在 `routes.py` 的请求分发**最前面**插入 License 状态检查，先于 auth 检查。

### 10.2 检查流程

```python
def _check_license_middleware(handler, parsed) -> bool:
    """Return True if request is allowed, False if blocked by license."""
    # 白名单：永远放行
    if parsed.path.startswith('/static/') or parsed.path.startswith('/session/static/'):
        return True
    if parsed.path == '/health':
        return True
    if parsed.path.startswith('/api/license/') or parsed.path == '/license' or parsed.path.startswith('/license/'):
        return True

    # 检查 license 状态
    from api.config import DEFAULT_WORKSPACE
    from api.license import check_license_status, init_license_config
    workspace = Path(DEFAULT_WORKSPACE)
    try:
        init_license_config(workspace)  # 确保 license.json 存在
        status = check_license_status(workspace)
    except Exception:
        return True  # license 模块异常时放行（向后兼容）

    license_state = status.get("status")

    # License 异常状态：拒绝
    if license_state == "expired":
        _send_403(handler, "License 已过期")
        return False
    if license_state == "copied":
        _send_403(handler, "License 检测到 MAC 变更")
        return False

    # License 未激活：重定向到激活页
    if license_state == "not_activated":
        if parsed.path.startswith('/api/'):
            handler.send_response(503)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(b'{"error":"License not activated"}')
        else:
            handler.send_response(302)
            handler.send_header("Location", "/license/activate")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
        return False

    # License valid：放行到下一层（auth/RBAC 检查）
    return True
```

### 10.3 集成点

在 `routes.py` 中替换现有的 `check_auth` 调用为：

```python
# 现有：
if not check_auth(handler, parsed):
    return

# 新增顺序：
if not _check_license_middleware(handler, parsed):
    return
if not check_auth(handler, parsed):
    return
```

### 10.4 不修改 License 业务逻辑

- **不改动** `api/license.py` 中任何现有函数
- License 状态查询、导入、激活等流程保持不变
- License API 路由（`/api/license/*`）保持不变

### 10.5 测试覆盖

| 测试场景 | 期望结果 |
|----------|----------|
| License 未激活，访问 `/login` | 302 → `/license/activate` |
| License 未激活，访问 `/api/license/status` | 200 |
| License 未激活，访问 `/health` | 200 |
| License `expired`，访问任意路径 | 403 |
| License `copied`，访问任意路径 | 403 |
| License `valid` + RBAC 未初始化，访问 `/login` | 302 → `/setup` |
| License `valid` + RBAC 已初始化，访问 `/login` | 显示登录页 |

---

## 11. 参考实现

- 豆包/元宝的会话分享模式
- Notion 的个人工作空间隔离
- Google Drive 的 ACL 分享模型
