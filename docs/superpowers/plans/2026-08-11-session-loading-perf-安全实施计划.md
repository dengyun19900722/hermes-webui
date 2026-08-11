# Session Loading 性能与身份隔离安全实施计划

**状态：** P0 观测层已落地，待采集基线；P1-P4 暂不实施
**日期：** 2026-08-11
**基线：** 当前 `master` 代码、`docs/rfcs/*` 契约，以及 2026-08-07 性能设计文档的评审结论

## 0. 当前实施进度（2026-08-11）

已完成 P0 的低风险代码准备，尚未改变任何缓存、分页、workspace、RBAC、SSE
或 session 状态行为：

- `api/request_diagnostics.py` 继续复用单 watchdog，覆盖本计划列出的 9 个 GET
  目标接口和 `POST /api/chat/start`；slow-request 记录增加请求阶段、响应状态和
  响应字节数。
- `server.py` 在请求入口、License middleware、auth middleware、handler 之间打
  阶段点；`api/helpers.py:j()` 在 JSON 序列化和写响应前打阶段点。
- profile、Cookie 和 user id 仅允许写入带 request id 盐的短哈希，禁止把原始身份
  或凭据写入诊断日志；HTTP/1.1 同一连接的请求序号仅作连接基线。
- `/api/sessions` 和 `/api/chat/start` 复用 server 创建的诊断对象，避免同一请求
  创建两个 watchdog；直接调用 route 的既有单测仍保留自建诊断兼容路径。

已验证：

- `./scripts/test.sh tests/test_issue1855_request_diagnostics.py
  tests/test_issue4973_diagnostics_watchdog.py tests/test_request_diagnostics_cache.py
  tests/test_license_middleware.py tests/test_license_middleware_integration.py
  --noconftest -q`：26 passed。
- `python3 -m py_compile api/request_diagnostics.py api/helpers.py api/routes.py
  server.py`：通过。
- `git diff --check`：通过。

下一步仅采集真实基线。未取得慢点的 stage、并发和连接证据前，不得开始 P1-P4
的实现；如 P0 发现诊断本身造成额外开销，应先关闭慢请求日志再继续。

## 1. 目标与非目标

### 目标

- 在不改变会话、workspace、RBAC、streaming 和 approval/clarify 行为的前提下，定位并降低会话打开延迟。
- 证明 4-500 个 session、多 tab、HTTP/1.1 keep-alive 和代理环境下的真实瓶颈。
- 保证用户切换、logout/login、BFCache 恢复和 profile 切换不会复用旧身份数据。
- 对确认有效的优化提供独立回滚开关和可观察指标。

### 非目标

- 不把 `/api/auth/status`、`/api/session/status` 或 workspace 数据做无作用域的全局缓存。
- 不改变 `msg_limit` 缺省值、`msg_before` 游标和完整历史加载语义。
- 不把 approval/clarify/session lifecycle 数据塞入现有全局 `/api/sessions/events`。
- 不在没有性能剖析证据前引入长期后台线程、通用缓存层或新的 SSE 总线。
- 不修改旧计划文件；旧计划中的建议仅作为待验证假设。

## 2. 硬性契约

以下契约在所有阶段都必须保持不变：

1. `/api/session?messages=0` 是 metadata-only 快速路径。
2. 显式 `msg_limit` 才启用尾部窗口；缺省或 full-history 调用仍能得到完整历史。
3. 浏览器响应必须绑定当前 request、Cookie、RBAC user 和 profile，缓存不得跨身份复用。
4. `/api/session/status` 的 `active_stream_id`、`agent_running` 和 live journal 状态必须是当前实时值。
5. `/api/sessions/events` 仍然只是全局、无敏感内容的 sidebar invalidation stream。
6. approval/clarify 事件必须按 session 订阅，并且只能到达有权查看该 session 的客户端。
7. workspace 响应中的空列表是有效状态，不得被 fallback 成其他用户或其他 profile 的 workspace。

## 3. 阶段总览

| 阶段 | 内容 | 风险 | 默认上线 |
|---|---|---:|---:|
| P0 | 根因测量、身份与连接基线 | 低 | 仅观测 |
| P1 | 会话读取路径低风险优化 | 低 | 是，需契约测试 |
| P2 | Dashboard 按配置缓存 | 中 | 否，灰度 |
| P3 | 仅对 profiling 证明慢的接口做定向优化 | 中 | 否，逐接口 |
| P4 | SSE/轮询连接预算评估和可选改造 | 高 | 默认不启用 |

每个阶段必须单独提交、单独验收、可独立回滚。任何阶段出现身份串号、workspace 越权、实时 turn 丢失或完整历史错误，立即停止后续阶段。

## 4. P0：测量与基线

### 4.1 需要采集的数据

- 在 `server.py` 请求入口、License middleware、auth middleware、目标 handler、锁等待和 response serialization 处分段记录耗时。
- 为 `/api/session/status`、`/api/approval/pending`、`/api/clarify/pending`、`/api/auth/status`、`/api/license/status`、`/api/health/agent`、`/api/crons/recent`、`/api/dashboard/status` 增加统一 request diagnostics。
- 记录 p50/p95/p99、状态码、响应大小、线程池使用量、HTTP keep-alive 数、SSE 连接数和 fallback 次数。
- 身份字段只记录不可逆 request-scoped hash；禁止日志输出 Cookie、token、workspace 路径中的敏感信息。

### 4.2 必须复现的场景

- 0、100、500 个 session；短历史和大历史各一组。
- 单 tab、3 tab、5 tab；一个 tab streaming、一个 tab terminal 的组合。
- HTTP/1.1 keep-alive 以及实际反向代理配置。
- test8 无 workspace、test11 无 workspace、test13 有 workspace 的连续登录切换。
- profile 切换、logout/login、BFCache back/forward。

### 4.3 P0 退出条件

- 明确慢点属于共享前置路径、`/api/sessions` 锁争用、目标 handler、响应写入还是浏览器连接排队。
- 没有 profiling 证据的接口不得进入 P3。
- 保存一份修复前基线报告，包含硬件、Python 版本、代理模式、session 数量和请求并发度。

## 5. P1：会话读取路径

### 5.1 保持现有分页语义

涉及：`api/routes.py` `/api/session` handler、`static/sessions.js`、`static/messages.js`。

- 保留当前初始流程：先 `messages=0`，再使用现有 `_INITIAL_MSG_LIMIT` 获取尾部窗口。
- 不把缺省 `msg_limit` 改为 200，也不把 `msg_limit=0` 解释成默认窗口。
- `_ensureAllMessagesLoaded()` 继续使用完整历史路径；不得为 fork、undo、编辑、重新生成、导出、outline 添加隐式上限。
- 继续使用 `_messages_truncated` 和 `_messages_offset`；如需增加 `has_more`，只能作为 additive 字段，不能替代旧字段。
- 审计所有 `messages=1` 调用，逐一标记为 `tail-window` 或 `full-history`，禁止只按 URL 字符串批量替换。

### 5.2 可接受的性能改动

- metadata-only 路径继续使用 `get_session(..., metadata_only=True)`。
- 只在 profiling 证明昂贵时，优化 metadata summary、model resolution、lineage merge 或 response serialization。
- 优先使用已有 `_index.json`、state.db summary 和 `route_session_list_cache.py` 的成熟逻辑，不新建重复索引层。
- 所有优化必须先添加 stage timing，再添加实现，避免把慢点隐藏在缓存命中率中。

### 5.3 P1 测试

- 0、30、200、500、1000 条消息的 tail-window 和 full-history 响应。
- `msg_before` 连续向前翻页无重复、无遗漏、游标单调。
- fork、undo、truncate/edit、regenerate、export、outline 在长历史上使用完整 transcript。
- streaming 中强制刷新、切换 session 和切换 profile，不得覆盖新 session 的 `S.messages`。

## 6. P2：Dashboard status 定向缓存

### 6.1 实现约束

涉及：`api/dashboard_probe.py`、`api/routes.py`、Dashboard 配置保存路径。

- 先实现按配置签名区分的短 TTL cache，签名至少包含 `enabled`、规范化 URL、`HERMES_WEBUI_HOST` 和配置写入版本。
- 保留 `never`、`always`、auto loopback probe、自定义 loopback URL、外部 browser URL 和非 loopback bind 行为。
- 使用 single-flight；请求线程读取上一次同配置结果，未就绪时返回明确 `pending`，不得把其他配置的结果当作当前结果。
- 配置保存成功后主动失效当前配置缓存，并在下一次请求或受控刷新时重新探测。
- 先不引入永久线程。只有 P0 证明请求线程探测是主要瓶颈后，才评估可停止、可重启、可观察的 daemon worker。

### 6.2 回滚与测试

- 保留 `HERMES_WEBUI_DASHBOARD_SYNC=1` 紧急同步路径。
- 测试在线、离线、timeout、invalid URL、`never`、`always`、custom URL、配置切换和 host 变更。
- 验证 100 个并发请求不会重复探测，也不会返回错误配置的 `browser_url`。
- `X-Cache` 必须通过 `j(..., extra_headers=...)` 注入，禁止直接在 `j()` 前调用 `send_header()`。

## 7. P3：定向状态优化

P3 只能逐接口上线，不能一次引入通用 `route_status_cache.py`。

### 7.1 `/api/auth/status`

- 默认不缓存；该接口包含当前用户身份、角色、panels、passkey 状态和 auth 设置。
- 如 profiling 证明 passkey/config 读取确实慢，拆分成“全局配置状态”和“当前请求身份状态”；身份状态必须绑定验证后的 session token hash、RBAC user id、profile 和配置版本。
- 添加 test8/test11/test13 keep-alive 切换、logout/login、Cookie 过期和并发请求测试。

### 7.2 `/api/session/status`

- 只允许缓存稳定 metadata；`active_stream_id`、`agent_running`、journal 和 pending 字段每次读取或通过实时 overlay 更新。
- 不允许 streaming hold-down 10 秒。
- 测试 server turn start、finish、SSE gap、hidden poll、服务重启后 stale stream id 不复活。

### 7.3 `/api/crons/recent`

- 缓存 key 必须包含 active profile、RBAC scope、`since` 和相关 cron generation。
- 缓存 builder 不得捕获已结束请求 handler。
- 测试未来 `since`、epoch `since`、profile 切换、cron 写入后立即可见。

### 7.4 `/api/health/agent` 与 `/api/license/status`

- 复用现有远程 health probe cache，不重复包装。
- License 优化必须覆盖 middleware 的共享前置路径，而不只是 `/api/license/status` 展示接口。
- 任何 shared cache 都必须证明 payload 不含用户身份或 workspace 权限信息。

### 7.5 通用缓存实现验收

- 不持锁等待 inflight event。
- 一个 key 同时只能有一个 builder；超时请求不得偷偷成为第二个 builder。
- invalidate generation 必须在 claim、build、commit 三个阶段检查。
- stale-while-revalidate 必须有 per-key single-flight，不能每次 stale 请求创建线程。
- builder 异常不得污染 cache；缓存命中不得跳过权限检查。

## 8. P4：SSE 与连接预算

### 8.1 默认方案

- 保持当前 approval/clarify per-session SSE 和 hidden-tab `/api/session/status` poll。
- 先做 poll in-flight 去重、visibility 停止、指数退避和连接数监控。
- 不修改现有全局 `/api/sessions/events` payload 类型和广播范围。

### 8.2 若确实需要 multiplex

必须先提交独立 RFC，定义：

- endpoint scope：user/profile/session；
- 初始 snapshot、命名 event、重连和 replay；
- approval/clarify payload 的 RBAC 过滤；
- session lifecycle 与 sidebar invalidation 的边界；
- HTTP/1.1、代理缓冲、服务重启和多 tab 连接预算。

实现时只能复用一个已有 EventSource；命名事件必须用 `addEventListener()` 接收，不能依赖 `onmessage`。旧路径必须保留到新路径完成端到端验收后再考虑删除。

## 9. 统一回滚与可观测性

- P1：前端 feature flag，可恢复原有明确 tail/full-history 请求。
- P2：`HERMES_WEBUI_DASHBOARD_SYNC=1`。
- P3：每个接口独立开关，禁止单个全局开关掩盖身份错误。
- P4：新 SSE 默认 off，fallback 必须可独立开启。
- 记录 cache hit/miss/stale、builder 次数、inflight wait、invalidate generation、SSE connect/reconnect、fallback 和权限拒绝计数。
- 所有指标按 endpoint、profile 和结果类型聚合，不记录 Cookie、token 或完整 workspace 路径。

## 10. 发布验收矩阵

### 身份与 workspace

- test8(无) → test11(无) → test13(有) → test8(无)。
- test13(有) → test3(有)，两个用户的 workspace、session、composer 和 file tree 互不残留。
- test11 创建唯一 workspace 后删除，立即显示空列表，不显示其他用户 workspace。
- logout/login、Cookie 轮换、HTTP keep-alive、BFCache 恢复后重新获取当前用户 workspace。
- profile 切换、页面刷新、多个 tab 同时切换，不接受旧请求覆盖新身份。

### 会话与实时状态

- 长历史 tail-window、load older、full-history 操作全部正确。
- visible/hidden tab 的 server-initiated turn 能启动、恢复、完成，不出现 ghost stream。
- approval/clarify 在已有 pending、创建、解决、取消和重连场景正确显示；不同用户不可见。

### 性能与网络

- 记录优化前后 p50/p95/p99，不以单纯 warmed-cache 命中作为唯一结论。
- HTTP/1.1 六连接、streaming + terminal、代理缓冲、SSE 断线和服务重启全部验证。
- 性能目标建议先设为“无回归 + 明确改善”，待 P0 基线完成后再冻结 `<1s` 和 `<200ms` 数值。

## 11. 提交顺序

1. `perf: add shared request stage diagnostics`
2. `test: add session/rbac/workspace switching matrix`
3. `perf: optimize proven session read stage`（仅包含 P0 证明的热点）
4. `perf: add config-scoped dashboard status cache`
5. 按接口分别提交状态优化，每个提交包含身份和失效测试。
6. 如需 SSE multiplex，先提交 RFC，再提交实现和端到端测试。

旧的 2026-08-07 计划保留为历史记录；本计划完成评审并通过 P0 基线后，才允许勾选实施任务。
