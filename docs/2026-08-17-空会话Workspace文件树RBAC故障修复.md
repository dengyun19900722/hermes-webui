# 空会话 Workspace 文件树 RBAC 故障修复

## 背景

2026-08-17 验证 workspace 申请链路后发现两个相关现象：

- 用户完成 workspace 申请后进入 chat 页，composer 已经选中该 workspace，但右侧文件树可能为空或展示上一账号/管理员可见的目录缓存。
- 本地以 admin 登录并默认选中 Home workspace 时，右侧 workspace 文件列表为空，页面没有发起有效目录加载。

该问题发生在“空聊天页已有当前 workspace、但还没有 active session”的状态。旧实现把右侧文件树绑定到 `S.session.workspace`，因此 session 为空时不会加载目录；同时后端文件浏览接口主要依赖 `session_id`，无法表达空会话只读浏览当前 workspace 的场景。

## 影响范围

- 空聊天页首次进入、刷新、BFCache 恢复后打开 workspace panel。
- workspace 申请通过后，当前账号已有可见 workspace 但尚未创建聊天 session。
- RBAC 多用户场景中，旧 session 或旧请求仍携带上一账号 workspace 时，右侧文件树存在展示错误目录的风险。
- 文件浏览 GET 接口：`/api/list`、`/api/file`、`/api/file/raw`。

写操作必须保持更严格边界：创建、删除、移动、上传等仍要求 session 绑定并通过当前调用者 RBAC 校验。

## 根因

1. 前端 `loadDir()` 在无 `S.session` 时直接退出，空聊天页即使 composer chip 已有 workspace，也不会请求 `/api/list`。
2. `renderFileTree()` 使用 `S.session.workspace` 判断是否有 workspace，导致“当前账号可见 workspace 存在、但 session 为空”被误判为空态。
3. 后端 `/api/list`、`/api/file`、`/api/file/raw` 只接受 `session_id`，没有空会话只读浏览当前 workspace 的安全入口。
4. session 可能保留旧 workspace。普通用户切换账号后，如果只按 session.workspace 读目录，存在读取非当前账号可见 workspace 的风险。
5. boot 阶段曾尝试为打开的 workspace panel 自动创建空 session，再把空 session 清掉，容易留下 session-mode 的文件树和写按钮状态。

## 修复方案

### 后端

- 新增请求级 workspace 解析：
  - `_workspace_scope_snapshot_for_caller()` 获取当前调用者可见 workspace 范围。
  - `_workspace_for_request_session()` 对 session.workspace 做 RBAC 校验，必要时回落到当前调用者可见的默认 workspace。
  - `_resolve_workspace_for_request_binding()` 校验显式传入 workspace 是否属于当前调用者可见范围。
  - `_workspace_read_view_from_query()` 支持 `session_id` 或显式 `workspace` 两种只读文件浏览入口。
- `/api/list`、`/api/file`、`/api/file/raw` 支持 `workspace=<path>`，用于空会话只读浏览；所有路径仍经过 trusted workspace 与 RBAC 校验。
- 文件写操作统一通过 `_get_session_for_workspace_file_ops()` 获取 session 视图，避免直接使用未经当前调用者校验的 session.workspace。
- `/api/file/raw` 在没有 `session_id` 的显式 workspace 浏览下，不再回退读取 session attachment inbox，避免空会话读取到会话附件。
- workspace upload 改为使用当前请求 RBAC 校验后的 session workspace。

### 前端

- `getCurrentWorkspaceBrowsePath()` 统一当前浏览 workspace 的来源：
  1. active session 的 workspace；
  2. 当前 profile 默认 workspace 且在可访问列表中；
  3. 当前账号可访问 workspace 列表第一项。
- `_workspaceRouteForPath()` 在无 session 时生成 `workspace=<path>` 的只读 GET 请求。
- `loadDir()` 支持 sessionless workspace browse，并增加 generation/current workspace guard，废弃账号切换中的旧请求响应。
- 空会话文件树强制只读：
  - 禁用新建、上传、删除、拖拽移动等写操作。
  - 右键菜单不展示需要 session_id 的写动作。
  - 刷新、上级目录、预览、下载可在只读浏览中继续工作。
- boot 阶段取消自动创建空 session，改为在 workspace panel 打开时直接加载 sessionless 文件树。
- 403 时清空文件树和预览，展示中文 warning toast，并刷新 workspace 列表，避免继续显示旧缓存。

## 风险控制

- 普通用户手写不可见 workspace path 调 `/api/list?workspace=...` 会返回 403，且不会进入底层 `list_dir`。
- 显式绑定不可见 workspace 会抛出 `WorkspacePermissionError`，不会修改原 session.workspace。
- 写接口仍要求 session_id；sessionless 模式只开放读取、预览、下载。
- worktree session 使用生成目录时保留例外：只要 session 本身对当前请求可见，其 `worktree_path` 仍可访问。
- RBAC 未启用时保持原有 trusted workspace 解析行为，避免单用户本地模式被误伤。

## 验证结果

### 自动化验证

| 验证项 | 结果 |
| --- | --- |
| `git diff --check` | 通过 |
| `python3 -m py_compile api/routes.py api/upload.py` | 通过 |
| `node --check static/workspace.js static/ui.js static/panels.js static/boot.js static/i18n.js` | 通过 |
| `./scripts/test.sh tests/test_workspace_rbac.py tests/test_workspace_rbac_integration.py --no-header -p no:cacheprovider --noconftest` | 19 passed |
| `./scripts/test.sh tests/test_file_manager_external_session.py tests/test_session_active_profile_authorization.py tests/test_workspace_blank_page_fix.py --no-header -p no:cacheprovider --noconftest` | 39 passed，1 个既有 pytest mark warning |

### Ego 浏览器验证结论

验证空聊天页、无 active session、workspace panel 默认打开的场景：

- `S.session === null`。
- composer chip 显示当前 workspace。
- workspace panel 为 browse 模式。
- 浏览器发起 `/api/list?workspace=...&path=.`，未自动发起 `/api/session/new`。
- 文件树成功渲染目录项。
- 空会话只读状态正确：新建文件、新建目录、上传按钮禁用；刷新按钮可用；删除按钮数量为 0。

该验证覆盖了本次线上现象的关键路径：没有 session 也能加载当前账号可见 workspace，同时不会把只读浏览升级成可写文件管理。

## 人工线上排查步骤

### 1. 保留前端现场

在浏览器 DevTools 中查看 Network：

- 过滤 `/api/workspaces`，确认响应只包含当前账号可见 workspace，且当前 workspace 在列表中。
- 过滤 `/api/list`，确认空会话页会发起 `workspace=<当前可见workspace>&path=.` 请求。
- 如果没有 `/api/list` 请求，优先排查前端 boot、workspace panel 状态、`getCurrentWorkspaceBrowsePath()`。
- 如果 `/api/list` 返回 403，优先排查当前用户的 workspace owner/members 配置、登录态是否切换完成、旧账号在途请求是否被废弃。
- 如果 `/api/list` 返回 200 但 UI 为空，检查返回 `entries` 是否为空；若不为空，继续排查 stale response guard、`renderFileTree()` 和浏览器控制台错误。

注意不要复制或外发 Cookie、Authorization header、密码、完整用户配置。

### 2. 查看 WebUI 后端日志

通过部署环境的服务管理方式读取 WebUI 日志，例如：

```bash
./ctl.sh logs --lines 300
```

重点搜索：

- `/api/list`、`/api/file`、`/api/file/raw` 的 403/404/500。
- `Workspace not accessible`。
- `Session not found`。
- `failed to persist workspace fallback`。
- 账号切换后仍出现上一账号 workspace path 的请求。

判断方式：

- 403 且 workspace 不在当前账号可见列表：RBAC 生效，检查前端是否仍使用旧 workspace。
- 403 但 workspace 应可见：检查 workspace owner/members、当前登录用户 id、Cookie 是否已经刷新。
- 404：检查 workspace path 是否还存在、是否通过 trusted workspace 校验。
- 500：保留 request id、时间点和堆栈，优先回滚或降级。

### 3. 核对 workspace 配置

在不泄露敏感信息的前提下，核对运行状态目录中的 workspace 配置：

- 当前账号 id 是否在 workspace `owner` 或 `members` 中。
- 删除唯一 workspace 后，列表是否返回显式空数组，而不是 fallback 到其他用户 workspace。
- admin 账号可见全部 workspace 是否符合预期；普通用户不应看到 admin-only workspace。

### 4. 用最小复现确认修复

推荐按以下顺序人工复测：

1. 普通用户无 workspace 登录，chat 页不显示其他用户目录。
2. 普通用户申请或创建唯一 workspace 后进入 chat 页，composer 选中该 workspace，右侧文件树能加载。
3. 空聊天页打开 workspace panel，确认没有自动创建空 session。
4. 在空会话文件树中确认新建、上传、删除、拖拽移动不可用。
5. 切换到 admin，再切回普通用户，确认右侧文件树不会残留 admin 目录。
6. 删除普通用户唯一 workspace 后，确认右侧文件树、composer、缓存立即清空。

## 回滚与观察点

如升级后出现大面积文件树不可用，可先观察：

- `/api/workspaces` 是否返回当前调用者可见列表。
- `/api/list?workspace=...` 是否为 403 或 404。
- 浏览器是否仍发旧式空 session 自动创建请求。
- 写操作是否误在 sessionless 模式开放。

必要回滚点：

- 前端可临时关闭 workspace panel 自动打开偏好，降低空会话路径触发频率。
- 后端如果 `/api/list?workspace=...` 出现非预期 500，应先回滚本次只读入口，同时保留写接口 RBAC 校验补丁，避免重新暴露越权风险。

## 后续建议

- 为浏览器端增加一条 headless smoke：空 localStorage、profile 有默认 workspace、workspace panel 打开时，应请求 `/api/list?workspace=...` 并渲染文件树。
- 在 `/api/list` 审计日志中增加脱敏后的 scope_user_id 与 workspace 解析结果，便于线上排查跨账号残留。
- 将 workspace panel 的 sessionless/read-write 状态做成显式 UI state，减少后续新增按钮时误开写操作的风险。
