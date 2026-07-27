# Chat Start 去重与 409 排查

- **状态：** 已实现
- **作者：** @dengyun
- **日期：** 2026-07-14
- **关联：** ZKREQ #5345 / #5198 / fresh-dedupe 后续

---

## 问题

`POST /api/chat/start` 在 `_start_chat_stream_for_session`（`api/routes.py:20427`）里有 4 个独立的 409 出口：

| `_source` | 行号 | 触发条件 |
|---|---|---|
| `session_active_stream_id` | 20514 | pre-lock 检查时 `active_stream_id` 已存在 |
| `session_active_stream_id_locked` | 20560 | 在 `session_lock` 内重检 |
| `active_runs` | 20577 | `_active_run_stream_for_session` 找到该 `session_id` 的活 worker |
| `stale_cleanup_failed` | 20604 | `_clear_stale_stream_state` 清理失败 |

旧服务器在抛出这些 409 时只附带 3 个字段的 `_diag`（`in_streams` / `in_active_runs` / `has_pending_user_message`），**无法区分**以下三种本质不同的场景：

- **卡死孤立 worker**（页面刷新 + 长 tool-call C 阻塞）— 持有 STREAMS / ACTIVE_RUNS 数分钟，需要主动 `cancel_stream()`
- **合法的正在运行的 turn** — 用户应等待
- **前端快速双发**（Enter + 点击 / SSE 重连 race / hung request 自动重试）— 第一个 `chat_start` 14ms 前已成功，第二个是用户没打算发的重复请求

第三种场景在生产中表现为 **"新开会话第一次输入就报这个错"**，是明显的"首条消息"体验故障，运维仅凭响应也排不出来。

## 目标

1. `_start_chat_stream_for_session` 的每个 409 都带上 **`diag_version: 2` 的真值形状**，运维一眼看出服务器是否加载了本次修复，以及触发决策的字段值
2. 在级联里加**第 5 道防线**：**新鲜流去重** —— 当 2 秒内到达重复 `chat_start`、且 worker 还在 `"starting"` 阶段时，返回 `200 + stream_id + _deduped: true`，让第二次请求静默挂到当前 turn 上
3. 保留原有的 `pending_started_at` 30s grace 与 `ACTIVE_RUNS[stream_id]["started_at"]` 兜底，让真正的卡死孤立 worker 继续被主动 `cancel_stream()` 路径处理
4. 对合法"用户等待后输入"场景（≥ 2s 或 `phase != "starting"`）继续返回 409，走 toast + 队列 UX

## 非目标

- 不新增端点，不改 `Session` schema，不改客户端 SDK
- 所有改动都在 `api/routes.py` + `api/streaming.py` 服务端，回归测试在 `tests/test_stale_stream_cleanup.py`
- 不动取消流程（`cancel_stream` 维持原状，除了之前打的 eager-`unregister_active_run` 补丁）
- 不动 SSE 流协议、不动 `_active_run_stream_for_session` 的 180s 上限

## 五道防线级联（按顺序）

进入 `if current_stream_id:` 分支后，依次执行；哪个先命中听哪个。

| # | 防线 | 触发条件 | 行为 |
|---|---|---|---|
| 1 | `pending_started_at` grace（30s） | `_effective_age_s >= 30s` | 主动 `cancel_stream()`，再开新流。信号：`_diag.past_grace: true` |
| 2 | `ACTIVE_RUNS[stream_id]["started_at"]` 兜底 | `pending_started_at` 为 0 / 缺失，但 `ACTIVE_RUNS` 里有 `started_at` | 同样做 age 检查，只是更稳的年龄代理。该字段由 `register_active_run()`（`api/config.py:7969`）的 `setdefault` 必设 |
| 3 | `cancel_stream()` eager unregister | 防线 1 触发的 `cancel_stream` 内部 | `update_active_run(phase="cancelling")` 后立刻 `unregister_active_run(stream_id)`，让后续 `chat_start` 不再被正在 `agent.interrupt()` 中解开的 worker 阻塞 |
| 4 | `_active_run_stream_for_session` 180s 上限 | `active_stream_id` 已清但 worker 卡死 | 180s 上限回收真正失联 / 僵尸 worker，避免永久 409 |
| 5 | **新鲜流去重**（新增） | `_effective_age_s < 2s` 且 `active_run_phase ∈ {None, "starting"}` | 返回 `200` + 现有 `stream_id` + `_deduped: true`，前端静默挂到当前 turn。信号：`_deduped: true, _dedup_age_s` |

防线 1 与防线 5 **按年龄互斥**：1 只在 ≥ 30s 触发，5 只在 < 2s 触发。2s–30s 之间、`phase != "starting"` 时走 409 路径（带新的 v2 `_diag`），这是合法的"用户等待后输入"窗口。

## v2 `_diag` 形状（每个 409）

```json
{
  "error": "session already has an active stream",
  "active_stream_id": "ff293c1cbb6845af9d7417dbd2d7c619",
  "_source": "session_active_stream_id",
  "_status": 409,
  "_diag": {
    "diag_version": 2,
    "in_streams": true,
    "in_active_runs": true,
    "has_pending_user_message": true,
    "pending_started_at": 1784015992.651438,
    "pending_age_s": 0.014505,
    "active_run_started_at": 1784015992.665618,
    "active_run_age_s": 0.000325,
    "active_run_phase": "starting",
    "active_run_session_id": "30928df6d842",
    "effective_started_at": 1784015992.651438,
    "effective_age_s": 0.014505,
    "orphan_grace_s": 30.0,
    "past_grace": false
  }
}
```

| 字段 | 含义 |
|---|---|
| `diag_version` | 修复后固定为 `2`。**缺失 → 服务器跑的是旧代码，必须重启 Python** |
| `in_streams` / `in_active_runs` | 原 3 字段 diag 的副本 |
| `has_pending_user_message` | 该 session 是否还有未确认的 user turn 落盘 |
| `pending_started_at` | session 落盘的 `pending_started_at`（由 `_persist_chat_start_state` 设置） |
| `pending_age_s` | `now - pending_started_at`。未设置则为 `null` |
| `active_run_started_at` | `ACTIVE_RUNS[stream_id]["started_at"]`，由 `register_active_run()` 设置 |
| `active_run_age_s` | `now - active_run_started_at`。无 ACTIVE_RUNS 条目则为 `null` |
| `active_run_phase` | `starting` / `running` / `tool_calling` / `cancelling` 等。`"starting"` 是去重门的开关 |
| `active_run_session_id` | ACTIVE_RUNS 条目里记的 `session_id` —— 通常一致，但排查跨 session 串扰时有用 |
| `effective_started_at` | `pending_started_at or active_run_started_at` —— grace 检查实际用的值 |
| `effective_age_s` | grace 检查实际用的年龄 |
| `orphan_grace_s` | grace 边界（默认 30s） |
| `past_grace` | 主动取消路径是否本应触发。`true` + 409 = 回归 |

## 409 排查速查表

| 信号 | 诊断 | 下一步 |
|---|---|---|
| **没有** `diag_version` 字段 | 服务器跑的是旧代码 | **重启 Python 后端**（仅 rebuild JS 不加载 Python 改动） |
| `active_run_phase: "starting"` + `effective_age_s < 2` | 前端双发 | 应被 fresh-dedupe 兜住（响应 `_deduped: true`）；若仍 409 说明服务器没加载去重 |
| `active_run_phase: "running"` + `effective_age_s < 30` | 合法的正在运行的 turn | 用户应等待；toast "Current session is still running. Reconnected and queued your message." 是预期行为 |
| `past_grace: true` + 409 | 主动 cancel 没触发 | 排查 `cancel_stream` 失败；常见于 SIGKILL 后的 worker 让 STREAMS / ACTIVE_RUNS 状态不一致 |
| `pending_started_at: 0` 且 `active_run_started_at: 0` | 两个年龄代理都为零；session 加载时没 `pending_started_at` 字段、且无 ACTIVE_RUNS 条目 | 去重 / grace / 取消都成空操作，运维需手动 `cancel_stream()` 再 `chat/start` |
| `effective_age_s >= 30` | 过期孤立 | 应被主动取消路径拆除；仍 409 说明 `cancel_stream` 坏了 |

## 实现要点

### `api/routes.py` — `_start_chat_stream_for_session`

- 把 v2 `_diag` 的所有年龄探针（`_in_streams` / `_in_active_runs` / `_active_run_started_at_diag` / `_active_run_phase` / `_pending_user_msg` / `_pending_started_at_diag` / `_grace_diag` / `_effective_diag` / `_pending_age` / `_active_age` / `_eff_age` / `_past_grace_diag`）**集中到一处计算**，让去重路径和 409 路径共用
- 新增去重门：`effective_age_s < 2.0` 且 `active_run_phase ∈ {None, "starting"}` 且 `current_stream_id` 存在 → 返回 `200` + 现有 `stream_id` + `_deduped: true, _dedup_reason: "fresh_stream_within_2s", _dedup_age_s: <float>`，INFO 日志记录 session / stream / age / phase
- 409 `elif` 复用已计算的值（无重复），发出完整 v2 `_diag`

### `api/routes.py` — `_active_stream_blocks_chat_start`

原 30s grace（20295 行）新增 `ACTIVE_RUNS[stream_id]["started_at"]` 兜底，处理 `pending_started_at` 未设 / 为 0 的情况（老 session 加载无此字段，或 `pending_*` 已被清但 worker 仍在 STREAMS 里活着）。这是新增防线 2 唯一落点。

### `api/streaming.py` — `cancel_stream`

原 docstring（10424 行）已更新，并新增 eager `unregister_active_run(stream_id)`（约 10530 行），让后续 `chat_start` 不再被正在 `agent.interrupt()` 中解开的 worker 阻塞。worker `finally` 也调 `unregister_active_run`，两边都 `.pop(key, None)`，重复 pop 是安全 no-op。

### `tests/test_stale_stream_cleanup.py`

新增 / 扩展：

- `test_chat_start_409_includes_v2_diag_with_age_and_grace` —— 源码级不变量（每个必填字段都在）+ 行为不变量（409 时响应带 `diag_version: 2` 且字段类型正确）
- `test_chat_start_dedupes_rapid_double_fire_within_2s` —— 去重行为：14ms + `"starting"` → `200 + _deduped: True + stream_id: <现有>`
- `test_chat_start_does_not_dedupe_running_stream` —— 回归保护：1s 老、`"running"` 阶段仍 409，不会被静默合并
- `test_chat_start_proactive_cancel_when_blocking_stream_is_stale` —— 已覆盖主动 cancel 路径，断言仍成立
- `test_cancel_stream_function_eagerly_unregisters_active_runs` —— 已覆盖 eager unregister 路径，断言仍成立

## 验收方法

1. **重启 Python 后端**（浏览器控制台的 `dirty hash: 87f3ef14` 是 JS service-worker 的哈希，不是 Python 进程）
2. 复现原始症状：开新会话、输入、发送。**应不再弹 409 toast**
3. 想强测 409 路径：跑一个长 turn，5 秒后再发一条 → 应 409，`_diag` 里 `diag_version: 2`、`active_run_phase: "running"`、`past_grace: false`，用户收到 "queued" toast（正确行为）
4. 想强测去重路径：开一个会话、发一条、立刻再发（比如双击发送）→ 第二次不应 409，devtools 网络面板里能看到 `_deduped: true`

## 上线

已在 `1.0.0-zk-ops` 分支合入。行为变更对 JS 端向后兼容：`_deduped: true` 的响应里仍有原 `stream_id` 字段，现有客户端代码直接 attach 即可，**无需 JS 改动**。v2 `_diag` 是纯加字段（3 个旧字段保留），读旧 `_diag` 的 JS / SDK 不受影响。
