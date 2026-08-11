# 会话数量达到 4-500 时 Loading Conversation 慢 — 修复设计文档

**版本：** v1.0
**日期：** 2026-08-07
**状态：** 待用户复核

---

## 1. 概述

### 1.1 背景

生产环境反馈：会话数量达到 4-500 个后，打开 / 切换会话时 "Loading conversation..." 加载很慢。后端日志显示大量接口单次耗时 **8-14 秒**，远超正常水平（< 200ms）。涉及 8 个高频接口：

| 接口 | 单次耗时样本（ms）|
|------|--------------------|
| `/api/session/status` | 7836 / 10066 / 10540 / 11073 / 11280 / 11396 / 11466 / 11756 / 11894 / 12321 / 14338 |
| `/api/approval/pending` | 11466 |
| `/api/clarify/pending` | 11519 |
| `/api/auth/status` | 12321 |
| `/api/license/status` | 2556 / 4757 / 4784 / 4784 / 6656 / 9699 |
| `/api/health/agent` | 11229 |
| `/api/crons/recent` | 10003 |
| `/api/dashboard/status` | 8494 |

日志时间戳：`2026-08-06T02:27:17Z`（remote）。

**关键观察**：不是单个接口慢，而是**所有 API 普遍 8-14 秒**，符合"每个请求都跑全量 IO + 解析"的现象，且**与 4-500 个会话量正相关**——会话越多越慢。

### 1.2 根因诊断

通过现状调研（routes.py、session_list_cache.py、session_events.py、dashboard_probe.py、agent_health.py、route_approvals.py、clarify.py、sessions.js、messages.js、ui.js、panels.js），定位到 4 类根因：

1. **`/api/sessions` 之外的高频接口全部冷调用** —— 仅 `/api/sessions` 走 `api/route_session_list_cache.py`（2.5s/10s TTL + source-stamp + in-flight dedupe + stale-while-revalidate），其他 8 个高频接口每次都全量计算（生产监控证据见 §1.1）。
2. **`/api/dashboard/status` 同步 HTTP 阻塞请求线程** —— `dashboard_probe.get_dashboard_status()` 在请求线程同步 `urllib.urlopen 127.0.0.1:9119`（0.5s timeout）。dashboard 不在线 / 被防火墙挡时每次 timeout 0.5s，前端 5s 轮询叠加。
3. **前端 3 处 setInterval 没切换到已就绪的 SSE** —— 后端 `/api/approval/stream`、`/api/clarify/stream`、`/api/session/stream` 都已存在 SSE（route_approvals.py、clarify.py、routes.py），但前端 `messages.js:6819` `setInterval(_tick, 1500)`、`messages.js:7014` `setInterval(tick, 6000)`、`messages.js:12417` 等仍在轮询。
4. **`/api/session?messages=1` 全量加载历史消息** —— `static/sessions.js:3308` 等路径调 `/api/session?messages=1` **不带 `msg_limit`**（虽然后端已支持 `msg_before/msg_limit` 分页），全量拉所有 messages，大消息会话是"loading conversation"慢的直接根因。

**叠加效应**：4 类根因在 4-500 个会话场景下同时爆发——请求线程被 dashboard 探测阻塞 + 高频接口冷调用 + SSE 闲置 + 全量消息加载 + 多 tab 轮询风暴 = 8-14s 现象。

### 1.3 目标

#### 短期（1-2 周）

| 成功指标 | 当前 | 目标 |
|---------|------|------|
| 打开会话 p95 | 8-14s | **< 1s** |
| 8 个高频接口 p95 | 8-14s | **< 200ms** |
| 多 tab 同步 | 重复拉数据 | **SSE 推送，不重复拉** |

#### 长期（1-2 周）

| 成功指标 | 当前 | 目标 |
|---------|------|------|
| 4-500 session 下 `list_sessions()` | 全量 `json.loads` | **< 50ms**（走 `_index.json`） |
| 启动时间 | 全量扫描 session dir | **< 1s** |

### 1.4 设计原则

- **复用现有模式**：所有缓存层都参考 `route_session_list_cache.py` 的 source-stamp + invalidation version 模型（这个模型已经在 #4672、#4808 等回归里被反复验证），降低新 bug 风险
- **不引入新依赖**：保持 stdlib + 现有第三方，不加 Redis / SQLite 客户端 / asyncpg / orjson
- **每 PR 可独立灰度回滚**：4 个短期 PR + 长期 PR 按依赖顺序部署，每 PR 都有 env 开关
- **充分利用已就绪的 SSE**：3 个 SSE 通道已存在，不要重新设计，只改前端订阅
- **JSON 不动**（长期方案）：用户偏好 `sessions/*.json` 保留，仅加 `_index.json` 侧车索引

### 1.5 不在范围内

- ❌ 不替换存储为 SQLite（用户决策：长期阶段 JSON 不动 + 索引）
- ❌ 不引入 Redis / 跨进程缓存（当前是单进程部署，进程内 LRU 足够）
- ❌ 不动 OAuth / auth_disabled_acknowledged 业务逻辑（只调整缓存层）
- ❌ 不改 license 校验算法（只缓存读路径）
- ❌ 不改 cron 调度算法（只缓存读路径 + 监听写事件）
- ❌ 不重构 ThreadingHTTPServer → ASGI（保持单进程多线程）
- ❌ 不引入前端框架替换（vanilla JS 保持）
- ❌ 不实现 SSE 重连退避（浏览器原生重连够用，必要时再加）

---

## 2. 架构

### 2.1 整体形态（不变）

- 单进程 `ThreadingHTTPServer`（server.py:173），每个请求一个 OS 线程
- Docker 端口 8787，进程内共享 LOCK + SESSIONS + SESSION_DIR
- 单进程 → **进程内 LRU 足够**，不需要多进程缓存共享
- 不引入新 Python 依赖

### 2.2 数据流

短期阶段引入 **4 个缓存失效源（active invalidate）+ 1 类被动失效（source-stamp TTL）**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                          写入侧（invalidator）                       │
│                                                                     │
│   settings 写   ──► _SETTINGS_WRITE_VERSION++ (已有)                │
│   license 写    ──► _status_cache_invalidate("license") 新增        │
│   cron job 写   ──► _status_cache_invalidate("cron") 新增           │
│   passkey 增删   ──► _status_cache_invalidate("auth") 新增          │
│   dashboard 探测 ──► 后台线程更新 _DASHBOARD_STATUS_CACHE            │
│                                                                     │
└─────────────────────────────┬───────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│   route_status_cache.py（新建，单进程 LRU + RLock）                  │
│  • PR3 覆盖 5 个高频接口共享 OrderedDict + source-stamp 失效         │
│  • PR2 独立处理 /api/dashboard/status（后台线程 + 缓存）             │
│  • approval/pending + clarify/pending 是内存状态，不进缓存          │
│  • TTL：默认 5s，auth/status 2s，license/status 10s                  │
│  • in-flight dedupe：同 key 并发请求合并                             │
│  • active invalidate：上述 4 类事件清除相关 key                      │
│  • metrics：hit/miss/invalidate/swr_stale 计数（debug log）         │
└─────────────────────────────┬───────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         读侧（endpoint）                            │
│ 5 个缓存接口 + 1 个 dashboard 异步 + 2 个内存状态查询                │
│ + 3 个 SSE 长连接（替代高频轮询，SSE push 模式不查 cache）          │
└─────────────────────────────────────────────────────────────────────┘
```

**SSE 流拓扑（短期 PR4 后）**：

| 已有 SSE（后端就绪、前端没用）| 改后用途 | 对应前端事件源 |
|------|------|------|
| `/api/sessions/events` | 侧边栏会话列表变更推送 | 已订阅（不需改） |
| `/api/approval/stream` | 替换 `setInterval(approval/pending, 1500ms)` | 改订阅 |
| `/api/clarify/stream` | 替换 `setInterval(clarify/pending, ...)` | 改订阅 |
| `/api/session/stream` | 替换 `setInterval(session/status, 6000ms)` | 改订阅 |

**`/api/dashboard/status` 异步探测**：

```
请求线程 ──► 读 _DASHBOARD_STATUS_CACHE（dict）───► 立即返回
                                          ▲
                                          │ 后台线程 5s 一次探测
                                          │ urllib.urlopen 127.0.0.1:9119
后台线程 ──► 探测结果写 _DASHBOARD_STATUS_CACHE
```

请求线程不再做 `urllib.urlopen`，dashboard 不在线时 0.5s × N 轮询的延迟累加彻底消除。

### 2.3 前后端模块分工

#### 后端（新建 2 个模块 + 修改 1 个模块）

| 模块 | 类型 | 职责 |
|------|------|------|
| `api/route_status_cache.py` | 新建 | 7 个高频接口的 TTL + source-stamp + active invalidate（参考 `route_session_list_cache.py`） |
| `api/dashboard_probe.py` | 修改 | 加后台探测线程 + `_DASHBOARD_STATUS_CACHE`，`get_dashboard_status()` 只读 |
| `api/startup.py` | 修改 | 启动后台 dashboard 探测线程 |
| `api/routes.py` | 修改 | 7 个高频接口加 `_status_cache_get(key, builder, ttl)` 包装 |
| `api/webui_session_db.py` | 修改（PR5+）| 加 `_index.json` 写入路径 + `list_sessions_from_index()` |

#### 前端（修改 2-3 个文件）

| 文件 | 改动 |
|------|------|
| `static/sessions.js` | `/api/session?messages=1` 路径补 `msg_limit=200` |
| `static/messages.js` | 3 处 `setInterval` 改 `EventSource`；提取 `_wireSSE()` 工具函数 |
| `static/messages.js` | 新增 fallback 轮询（EventSource 重连失败时降级） |
| `static/messages.js` | 把 3 个新 SSE 合并到 `/api/sessions/events` 多路复用（避免 Chrome 6 个连接上限） |

---

## 3. 短期阶段（4 个 PR）

按"风险从小到大 + 可独立回滚"分 4 个 PR。

### 3.1 PR1：msg_limit 强制分页（最小风险，~1-2 天）

#### 动机
用户打开会话时 `loadSession()` 流程中 `static/messages.js:3308`、`static/sessions.js:1429`、`static/sessions.js:2504` 等路径调 `/api/session?messages=1` **不带 `msg_limit`**，全量拉所有 messages。会话消息量大时这是"loading conversation"慢的最直接根因。

#### 现有能力（已就绪）
- `/api/session` 后端已支持 `msg_before=<idx>&msg_limit=<n>`（routes.py 模型层已有）
- 前端 `_ensureMessagesLoaded()` 部分路径已用 `msg_before/_INITIAL_MSG_LIMIT`

#### 改动

| 文件 | 改动 |
|------|------|
| `api/routes.py`（`/api/session` handler）| 后端默认 `msg_limit=200`（可被 query 参数覆盖），超过则用"最近 200 条 + has_more=true" |
| `api/routes.py`（同 handler）| 把 `msg_before/msg_limit` 透传给 `Session.get_messages_page()`（若不存在则实现） |
| `static/sessions.js` | 所有 `/api/session?messages=1` 路径都补传 `msg_limit=200`，加载后渲染检查 `has_more` 决定是否显示"加载更早" |
| `static/messages.js` | 同上，验证 `messages.js:3308` 等路径 |

#### 行为契约
- `msg_limit=0` 或缺省 = 后端默认 200
- 返回 `{messages: [...], has_more: bool, total_count: int}`
- 旧客户端不带 `msg_limit` 仍兼容（默认 200 而不是报错）

#### 风险 / 回滚
- 风险：极低。增量改动，旧路径保持兼容。
- 回滚：删除 `msg_limit` 默认值即可。

#### 测试
- 单元：消息数 < 200 / = 200 / > 200 的三种情况
- 集成：前端从空 tab 打开大消息会话（1000 条），验证只拉 200 + 显示"加载更早"
- 性能：500 消息会话打开 < 1s

---

### 3.2 PR2：`/api/dashboard/status` 异步化（~1 天）

#### 动机
`dashboard_probe.get_dashboard_status()` 在请求线程同步 `urllib.urlopen 127.0.0.1:9119`（0.5s timeout）。dashboard 不在线 / 被防火墙挡时每次 timeout，前端每 5s 轮询叠加，配合其他慢点形成 8-14s 现象。

#### 改动

| 文件 | 改动 |
|------|------|
| `api/dashboard_probe.py` | 新增模块级 `_DASHBOARD_STATUS_CACHE: dict`，加 `_DASHBOARD_PROBE_THREAD` daemon 线程，启动时跑一次探测，之后每 5s 一次 |
| `api/dashboard_probe.py` | `get_dashboard_status()` 改成只读 `_DASHBOARD_STATUS_CACHE`，不再调 urllib；缓存未就绪时返回 `{"running": False, "pending": True}` |
| `api/startup.py` | 在 `fix_credential_permissions()` 之后启动后台探测线程（daemon=True） |
| `api/dashboard_probe.py` | 加 thread-safe 写（Lock），加优雅停机（atexit 标志） |

#### 行为契约
- 首次启动有 ~50ms 探测窗口返回 `pending=True`
- 探测失败 / 超时返回 `running=False` + 缓存写入，5s 后重试
- 配置变更（`webui.dashboard.enabled/url`）走 `publish_dashboard_config_changed()` 立即触发一次探测

#### 风险 / 回滚
- 风险：低。同步 → 异步只影响一个 endpoint。
- 回滚：保留原 `probe_official_dashboard()` 函数，加 `force_sync=False` 走缓存、`force_sync=True` 同步（紧急开关，env `HERMES_WEBUI_DASHBOARD_SYNC=1`）。

#### 测试
- 单元：探测成功 / 失败 / 超时 / 网络异常四种
- 集成：dashboard 在线 / 离线时请求 `/api/dashboard/status` < 50ms
- 线程安全：100 个并发请求全拿到同一份缓存

---

### 3.3 PR3：5 个高频接口 TTL 缓存（~3-5 天，最大工作量）

#### 动机
除 `/api/sessions` 已有 `route_session_list_cache.py` 外，监控中的 8 个慢接口里：
- `/api/dashboard/status` 由 PR2 独立处理（后台线程 + 缓存）
- `/api/approval/pending` 和 `/api/clarify/pending` 是内存状态查询，PR4 后改 SSE 推送
- 剩下 **5 个**（`/api/session/status`、`/api/auth/status`、`/api/license/status`、`/api/health/agent`、`/api/crons/recent`）加 TTL 缓存。后端日志里 8-14s 全军覆没，符合"每个请求都跑一遍 IO + 解析"的现象。

#### 改动

| 文件 | 改动 |
|------|------|
| `api/route_status_cache.py`（新建）| 复用 `route_session_list_cache.py` 模式：单进程 OrderedDict + RLock + source-stamp + in-flight dedupe + stale-while-revalidate |
| `api/route_status_cache.py` | 暴露 `_status_cache_get(key, builder, ttl, allow_stale)`、`_status_cache_invalidate(reason)`、`_status_cache_clear()` |
| `api/routes.py`（5 个高频接口）| 包一层 `_status_cache_get(key, builder=..., ttl=...)` |
| `api/license.py` | license 写时调 `_status_cache_invalidate("license")` |
| `api/auth.py` | passkey 注册 / 删除、`auth_disabled_acknowledged` 变更时 invalidate |
| `api/agent_health.py` | 后台线程写 `_GATEWAY_RUNTIME_STATUS` 后 invalidate |
| `api/crons/*` | cron job 写时 invalidate（用现有 listener）|
| `api/route_approvals.py` | `submit_pending` / `_handle_approval_respond` 后调 `_status_cache_invalidate("approval")`（仅 metrics，approval 本身不缓存）|
| `api/clarify.py` | 同上 |

#### 缓存策略表（每个接口的 key / TTL / 失效源）

| 接口 | TTL | key 组成 | 主动失效源 |
|------|-----|---------|----------|
| `/api/license/status` | 10s | `license-config-path-mtime` | license 写 |
| `/api/auth/status` | 2s | `passkeys-mtime` + `_SETTINGS_WRITE_VERSION` | passkey 增删 + auth_disabled_acknowledged 改 |
| `/api/health/agent` | 3s | `gateway_state.json-mtime` + `gateway.pid-mtime` | 后台线程写 `_GATEWAY_RUNTIME_STATUS` |
| `/api/dashboard/status` | — | 由 PR2 处理（独立后台线程 + 缓存） | 后台线程每 5s 更新 |
| `/api/crons/recent` | 5s | `cron-jobs-mtime` | cron job 写 |
| `/api/session/status` | 2s（streaming 时 10s）| `session.json-mtime` + `_active_state_db_fingerprint` | streaming 状态变更 |
| `/api/approval/pending` | 不缓存 | — | — |
| `/api/clarify/pending` | 不缓存 | — | — |

> **为什么 approval/clarify 不缓存**：两者是内存状态查询（`_pending` dict，O(1)），加缓存反而引入失效复杂度。原 1500ms 轮询在 PR4 后改为 SSE 推送，问题自然消失。

#### source-stamp 模型（关键决策）
- **不是** TTL-only，也不是文件 mtime-only
- 是 **TTL（保兜底）+ 文件 mtime（秒级失效）+ active invalidate（即时失效）** 三层组合
- 这避免"license 改了但 TTL 未到导致拿到旧数据"

#### 行为契约
- 5 个接口都返回 `X-Cache: HIT/MISS/STALE` 响应头（debug 用）
- DEBUG 日志输出 hit/miss/invalidate 计数（每分钟汇总一次）
- 缓存未就绪或 builder 抛错时返回 500（与现状一致），不静默吃错

#### 风险 / 回滚
- 风险：中等。需要监听多类写事件。但每类监听都是局部、低侵入。
- 回滚：env `HERMES_WEBUI_DISABLE_STATUS_CACHE=1` 全局关闭；删除 `_status_cache_get()` 包装层即可，无 builder 改动。

#### 测试
- 单元：5 个接口的 cache hit/miss/invalidate 路径
- 单元：TTL 到期、source-stamp 变化、active invalidate 三种失效场景
- 集成：模拟 settings/license/cron 写，验证下一次请求拿到新数据
- 并发：100 并发同一 key，验证 in-flight dedupe 不重复 build
- 性能：5 个高频接口 p95 < 200ms

---

### 3.4 PR4：3 处 setInterval 改 SSE（~3-5 天，前端主战场）

#### 动机
后端 SSE 全部就绪（`/api/approval/stream`、`/api/clarify/stream`、`/api/session/stream`），但前端 3 处 `setInterval` 没切换，是 SSE 化的最大杠杆。

#### 改动

| 文件 | 改动 |
|------|------|
| `static/messages.js:6819` `_approvalPollTimer = setInterval(_tick, 1500)` | 改订阅 `/api/approval/stream`（已存在）|
| `static/messages.js:7014` `_sessionStreamHiddenPollTimer = setInterval(tick, 6000)` | 改订阅 `/api/session/stream`（已存在）|
| `static/messages.js` clarify polling | 新建 EventSource 订阅 `/api/clarify/stream` |
| `static/messages.js` 通用 | 提取 `_wireSSE(url, onMessage, onError, fallbackInterval)` 工具函数，复用 SSE 模式 |
| `static/messages.js` | EventSource 失败时降级 HTTP 轮询，重连成功后停 fallback |

#### 行为契约
- EventSource 关闭时（断线）自动重连（浏览器原生）
- EventSource 长时间没消息时（> 30s）触发重连（同 native keepalive）
- 后端 SSE 主动 close 时（服务重启），EventSource 立即重连
- onError 时降级 fallback 1500ms/6000ms 轮询，EventSource 重连成功后停掉 fallback

#### 连接数审计（关键风险：Chrome 6 个连接上限）

PR4 实施前必做：

| EventSource | 数量 |
|------|------|
| `/api/sessions/events`（sidebar 列表变更）| 1 |
| `/api/sessions/gateway/stream`（gateway 状态）| 1 |
| `/api/chat/stream?stream_id=xxx`（消息流）| 1（仅 streaming 时）|
| `/api/approval/stream`（PR4 新增）| 1 |
| `/api/clarify/stream`（PR4 新增）| 1 |
| `/api/session/stream`（PR4 新增，替代 6s 轮询）| 1 |
| **常态** | **5** |
| **streaming 时** | **6**（临界）|
| **streaming + terminal 同时** | **7+**（超 Chrome 上限）|

**处理策略（推荐）**：把 `/api/approval/stream`、`/api/clarify/stream`、`/api/session/stream` 合并到 `/api/sessions/events` **多路复用**（新加 event type `approval` / `clarify` / `session_status`）。这样总连接数仍为 5-6，不超 Chrome 上限。

具体做法：
1. `api/session_events.py` 新增 `publish_approval_event()` / `publish_clarify_event()` / `publish_session_status_event()`，复用 `_SESSION_EVENTS_SUBSCRIBERS` Queue
2. `api/route_approvals.py` `_approval_sse_notify` 改为同时调 `publish_approval_event()`（兼容旧 `/api/approval/stream` 端点过渡）
3. `api/clarify.py` 同上
4. 后端 `/api/sessions/events` 增加事件类型分发，前端订阅一个总线即可
5. 旧的 `/api/approval/stream` 等 SSE 端点保留但标记 deprecated，1-2 个版本后删除

#### 风险 / 回滚
- 风险：中等。前端 EventSource 多了，通过多路复用控制连接数；fallback 保证兼容性。
- 回滚：旧版 JS 文件保留为 `messages.js.bak`，可一键回切；env `HERMES_WEBUI_DISABLE_SSE_FALLBACK=1` 关闭 fallback（保留旧轮询）。

#### 测试
- 单元：3 个 SSE fallback 路径（连接断开、协议错、超时）
- 集成：批准一个 approval，3 秒内 UI 卡片更新（不再是 1500ms 轮询延迟）
- 多 tab：同时开 5 个 tab，每个都各自 SSE 推送，验证不重复拉
- 性能：8 个高频接口 p95 < 200ms，前端轮询次数降到 0（除 fallback）

---

## 4. 长期阶段（PR5+）：`_index.json` 侧车索引，~1-2 周

### 4.1 动机
`api/webui_session_db.py` 的 `list_sessions()` 每次都 `self.session_dir.glob("*.json")` + `json.loads(path.read_text(...))`，4-500 个文件就是 4-500 次磁盘 IO + JSON 解析。`_index.json` 已经在 `_session_list_cache_source_stamp` 里被 stat 引用（`route_session_list_cache.py:391`），但**当前不一定真存在** —— 需要补全写入路径。

### 4.2 索引结构

`SESSION_DIR/_index.json`：

```json
{
  "_version": 12345,
  "_written_at": 1723123456.789,
  "sessions": {
    "<sid>": {
      "title": "...",
      "workspace": "...",
      "model": "...",
      "model_provider": "...",
      "created_at": ...,
      "updated_at": ...,
      "pinned": true,
      "archived": false,
      "message_count": 42,
      "last_message_at": ...,
      "is_cli_session": false,
      "source_tag": "webui"
    }
  }
}
```

只存 metadata，**不存 messages**。`read_session(sid)` 仍直接读 sid.json。

### 4.3 写入路径

| 触发点 | 行为 |
|------|------|
| `Session.create()` / `Session.save()` | 写 session JSON 后调 `_update_session_index(sid, fields)` |
| `Session.delete()` | 调 `_remove_session_index(sid)` |
| `Session.archive()` / `Session.rename()` / `Session.pin()` | 同上（update_metadata 已能覆盖）|
| 写入顺序 | 先写 sid.json，再写 _index.json（索引失败不影响主流程）|
| 写索引失败 | log error，下次启动 `rebuild` 重建 |

### 4.4 读取路径

| 接口 | 行为 |
|------|------|
| `list_sessions()` | 默认走 `list_sessions_from_index()`（O(1) 文件读 + 内存 dict 遍历）|
| 索引缺失时 | 降级到原 `glob + loads`（兼容老版本）|
| `read_session(sid)` | 不变（直接读 sid.json） |
| 启动时 | 如果 `_index.json` 不存在 → 触发 `rebuild_session_index_from_disk()` |
| 启动时 | 如果 `_index.json` mtime 旧于任一 `*.json` mtime → 触发全量重建 |

### 4.5 改动

| 文件 | 改动 |
|------|------|
| `api/webui_session_db.py` | 新增 `_update_session_index(sid, fields)` / `_remove_session_index(sid)` / `_rebuild_session_index()` |
| `api/webui_session_db.py` | `update_metadata()` / `archive()` / `write_session()` 写 session JSON 后同步写 `_index.json` |
| `api/webui_session_db.py` | 新增 `list_sessions_from_index()` |
| `api/webui_session_db.py` | 新增 `rebuild_session_index_from_disk()`（启动时调用） |
| `api/webui_session_db.py` | 加 `_INDEX_FIELDS = frozenset({title, workspace, model, ...})` |

### 4.6 行为契约
- 索引最终一致：write path 双写，失败不破坏主流程
- 读 path 默认走索引；索引缺失时降级到原 `glob + loads`
- `Session.compact()` 不动（compact 已只返回 metadata）

### 4.7 风险 / 回滚
- 风险：中等。需要覆盖所有 session 写路径；写失败要可观察（启动重建兜底）。
- 回滚：env `HERMES_WEBUI_DISABLE_SESSION_INDEX=1` 关闭索引路径，回到 `glob + loads`。

### 4.8 测试
- 单元：单写 / 批量写 / 失败回滚 / 启动重建 4 种路径
- 集成：4-500 个 session 启动 < 1s（原来 8s+），冷启动后 `list_sessions()` < 50ms
- 并发：100 个写并发 + 100 个读并发，索引一致
- 兼容：从老版本（无索引文件）升级，验证启动后索引正确重建

---

## 5. 测试策略

| 阶段 | 测试类型 | 工具 | 覆盖点 |
|------|---------|------|--------|
| 单元 | pytest | pytest + monkeypatch | cache hit/miss/invalidate、SSE 消息格式、索引写失败回滚、dashboard 线程安全 |
| 集成 | pytest + Flask test client | `python -c` 模式（conftest 阻塞） | 5 个 PR3 缓存接口 + 1 个 PR2 dashboard + 3 个 PR4 SSE 端到端 + cache TTL 到期后数据正确 |
| 性能 | pytest + time.monotonic | 模拟 4-500 session 目录 | 短期 PR1-4 后 5 个高频接口 p95 < 200ms（dashboard < 50ms）、打开会话 < 1s；长期 PR5+ 后启动 < 1s |
| 端到端 | tmux 启动真服务 + playwright/curl | tmux | 3 个 SSE fallback、多 tab 同步、approval/clarify 端到端 |
| 回归 | conftest 服务 + license 健康 | 现有 `conftest.py test_server` | license gate 不被破坏、`/health` 仍 200、auth gate 仍生效 |
| 一致性 | 双写一致性 | pytest | 写 session JSON 失败 → 索引不更新；写索引失败 → 下次启动重建 |

### 5.1 性能基准（必测）

- `bench_session_load.py`：生成 500 个 session，测量 `list_sessions()` 时间
- `bench_high_freq.py`：5 个 PR3 缓存接口 + 1 个 PR2 dashboard 各跑 1000 次，统计 p50/p95/p99
- `bench_open_conversation.py`：500 session 下，打开第 250 个，测量 `loadSession()` 完整流程

---

## 6. 错误处理

| 场景 | 处理 |
|------|------|
| cache builder 抛错 | 缓存层捕获 → 返回 500（与现状一致）+ log builder traceback + 不污染 cache 状态 |
| cache 损坏（OrderedDict 状态错乱）| 加 startup self-check，损坏时 `_status_cache_clear()` 重建 |
| SSE EventSource 断线 | 浏览器原生重连（默认 3s），加重连退避（3s/6s/12s 上限 30s）+ EventSource 重连成功后停 fallback 轮询 |
| SSE 后端 close（服务重启）| 同上 native 重连 |
| dashboard 后台探测线程崩 | daemon=True 不拖死服务；下次 `get_dashboard_status()` 检查线程 alive，死了重启 |
| 索引写失败 | 主流程不中断；log error；下次启动重建 |
| license/cron/passkey 写并发与 invalidate race | 用 RLock + invalidation version（参考 `_session_list_cache_source_stamp` 模式），不会出现"写了但 cache 还在用旧值" |
| TTL 到期但 source-stamp 未变 | 重新 build builder，正常 path |

**关键设计**：**所有缓存层都参考 `route_session_list_cache.py` 的 source-stamp + invalidation version 模型**——这个模型已经在 #4672、#4808 等几个回归里被反复验证过，直接复用降低新 bug 风险。

---

## 7. 部署策略

### 7.1 每 PR 独立部署

| PR | 部署顺序 | 灰度策略 | 回滚开关 |
|----|---------|---------|---------|
| PR1 msg_limit | 第 1 批 | 全量（极低风险） | `msg_limit=0` 关闭分页 |
| PR2 dashboard 异步 | 第 2 批 | 全量 | env `HERMES_WEBUI_DASHBOARD_SYNC=1` 走同步 |
| PR3 高频缓存 | 第 3 批 | 全量 | env `HERMES_WEBUI_DISABLE_STATUS_CACHE=1` |
| PR4 SSE 化 | 第 4 批 | 灰度：新前端 + 旧前端并存 1 周，确认无 fallback 误触发 | 旧版 JS 文件保留为 `messages.js.bak`，可一键回切 |
| PR5+ 索引 | 第 5+ 批 | 灰度：写双写、读索引；读路径开关 `HERMES_WEBUI_USE_SESSION_INDEX=1/0` 默认 off | env 关闭索引读 |

### 7.2 Observability（每 PR 必带）

- 日志：`[route_status_cache] hit=N miss=M invalidate=I swr_stale=S` 每分钟汇总
- 响应头：`X-Cache: HIT/MISS/STALE`（debug 用，生产可关）
- SSE metrics：连接数 / 重连次数 / fallback 触发次数（每分钟 log）
- dashboard 后台线程：探测耗时 / 失败次数 / 缓存更新次数

### 7.3 生产环境回归验证（每 PR 后）

- 5 个 PR3 缓存接口 p95 < 200ms，1 个 PR2 dashboard 接口 < 50ms（已有 8-14s 基线，对比明显）
- 打开会话 p95 < 1s
- 1 个 tab streaming + 3 个 tab 后台 → SSE 总数 < 6（多路复用后）
- 多 tab 同步：approval / clarify 在 3 个 tab 同时显示 / 消失

---

## 8. 风险总览

| 风险 | 等级 | 缓解 |
|------|------|------|
| PR3 缓存引入过期数据（license / auth / cron 改后 cache 未失效）| 中 | active invalidate 三层（mtime + write event + TTL）+ env 开关 |
| PR4 SSE 多连接超 Chrome 6 上限 | 中 | 多路复用 `/api/sessions/events`（推荐方案已选）|
| PR5+ 双写一致性 | 中 | 写索引失败不破坏主流程 + 启动重建兜底 |
| 生产环境 dashboard 不在 / 网络隔离 | 低 | PR2 后台探测失败只 `running=False`，不影响主功能 |
| EventSource 与浏览器 / 代理不兼容 | 低 | fallback HTTP 轮询 + 旧前端保留 1 周 |
| 多 worker / 多实例（如果未来部署）| 低 | 当前是单进程 ThreadingHTTPServer，进程内 LRU 足够；未来如果要扩多 worker，缓存层接口已抽象 |

---

## 9. 跨阶段依赖

```
PR1 msg_limit  ─► PR2 dashboard 异步 ─► PR3 高频缓存  ─► PR4 SSE 化  ─► PR5+ 索引
   无依赖             无依赖              依赖 PR2            依赖 PR3        依赖 PR1-4
```

建议按依赖顺序部署，每 PR 后跑回归（pytest + tmux 端到端）。

---

## 10. 关键文件索引（方便 plan 阶段定位）

| 文件 | 改动类型 | 涉及章节 |
|------|---------|---------|
| `api/routes.py` | 修改 | §3.1 / §3.3 |
| `api/dashboard_probe.py` | 修改 | §3.2 |
| `api/startup.py` | 修改 | §3.2 |
| `api/route_status_cache.py` | **新建** | §3.3 |
| `api/license.py` | 修改 | §3.3 |
| `api/auth.py` | 修改 | §3.3 |
| `api/agent_health.py` | 修改 | §3.3 |
| `api/route_approvals.py` | 修改 | §3.3 / §3.4 |
| `api/clarify.py` | 修改 | §3.3 / §3.4 |
| `api/session_events.py` | 修改 | §3.4（多路复用 SSE）|
| `api/webui_session_db.py` | 修改 | §4 |
| `static/sessions.js` | 修改 | §3.1 |
| `static/messages.js` | 修改 | §3.1 / §3.4 |
| `tests/bench_*.py` | **新建** | §5.1 |

---

## 11. 文档元数据

- **作者**：ZK 运维智能体
- **关联问题**：生产环境 P0 · 会话多时 Loading Conversation 慢
- **关联计划文档**：`docs/superpowers/plans/2026-08-07-session-loading-perf-plan.md`（下一步 writing-plans skill 生成）
- **关联分支**：`1.0.0-zk-ops`