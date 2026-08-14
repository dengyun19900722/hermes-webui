# 2026-08-14 ToolEntry 动态 Schema 升级兼容故障修复

## 1. 背景

线上升级后，Chat 页面在使用 `qwen3.6-27b` 发起会话时出现异常，回答无法正常生成。页面错误核心信息为：

```text
'ToolEntry' object has no attribute 'dynamic_schema_overrides'
```

现场临时验证发现：把 `api/streaming.py` 约 309 行的 `dynamic_schema_overrides=entry.dynamic_schema_overrides` 注释掉后，Chat 恢复正常。

本次修复目标：

1. 保证升级后的 Hermes Agent `ToolEntry` 缺少 `dynamic_schema_overrides` 字段时，WebUI Chat 主链路不崩溃。
2. 保留旧版本或带该字段版本的动态 schema 能力，不用简单注释导致能力静默丢失。
3. 用回归测试锁住兼容行为，避免后续升级再次打断 streaming 运行链路。

安全约束：本文不记录线上账号密码、Cookie、token、完整请求头或任何可复用凭据。

## 2. 影响范围

影响场景：

- 升级到某些 Hermes Agent 版本后，`tools.registry` 返回的 `ToolEntry` 不再包含 `dynamic_schema_overrides` 字段。
- WebUI Chat 启动 streaming worker 时会安装 cronjob profile wrapper。
- wrapper 重新注册 cronjob tool 时直接读取缺失字段，导致 Python `AttributeError`。

用户可见症状：

- Chat 页面输入问题后，模型没有正常流式回答。
- 页面出现 provider/runtime 类错误提示。
- 看起来像 `qwen3.6-27b` 模型不可用，但实际根因发生在模型调用前的工具注册兼容层。

不属于本次故障范围：

- `qwen3.6-27b` 模型本身连通性。
- 前端 SSE 自动滚动。
- Settings、Providers、Knowledge 页面慢请求。

## 3. 时间线

- 线上升级后：用户在 Chat 页面使用 `qwen3.6-27b` 发现回答生成失败。
- 现场定位：截图显示异常为 `ToolEntry` 缺少 `dynamic_schema_overrides`。
- 临时规避：注释 `api/streaming.py` 约 309 行后恢复正常。
- 根因确认：WebUI 的 cronjob profile wrapper 复制旧工具条目元数据时，对可选字段使用了强依赖读取。
- 修复落地：改为构造基础注册参数，并仅在旧条目实际存在 `dynamic_schema_overrides` 时转发。
- 回归验证：新增缺字段 `ToolEntry` 测试；定向测试通过。
- 代码提交：`d6d65196 fix(streaming): 兼容缺少 dynamic_schema_overrides 的 ToolEntry`。

## 4. 根因分析

### 4.1 故障发生位置

文件：`api/streaming.py`

函数：`_install_streaming_cronjob_profile_wrapper()`

该函数的职责是在 WebUI streaming 运行期间，为 Hermes Agent 的 `cronjob` tool handler 包一层 profile-aware context，使 cronjob 工具调用读取当前 WebUI profile 的 cron 数据，而不是误读进程默认 `HERMES_HOME`。

### 4.2 修复前代码

修复前注册逻辑直接复制 `entry.dynamic_schema_overrides`：

```python
registry.register(
    name=entry.name,
    toolset=entry.toolset,
    schema=entry.schema,
    handler=_profile_scoped_cronjob_handler,
    check_fn=entry.check_fn,
    requires_env=entry.requires_env,
    is_async=entry.is_async,
    description=entry.description,
    emoji=entry.emoji,
    max_result_size_chars=entry.max_result_size_chars,
    dynamic_schema_overrides=entry.dynamic_schema_overrides,
)
```

当升级后的 `ToolEntry` 没有 `dynamic_schema_overrides` 属性时，代码在注册前就抛出：

```text
AttributeError: 'ToolEntry' object has no attribute 'dynamic_schema_overrides'
```

由于该安装动作发生在 agent streaming worker 启动阶段，异常会阻断 Chat 主流程，表现为模型没有正常回答。

### 4.3 为什么注释后能恢复

注释该行后，代码不再读取缺失属性，因此 `registry.register()` 可以继续执行，Chat 主流程恢复。

但直接注释不是稳健修复：

- 如果某些 Hermes Agent 版本仍然提供 `dynamic_schema_overrides`，WebUI 会丢失该动态 schema 元数据。
- 该行为属于跨版本兼容，不应通过永久删除能力字段解决。

正确策略是：字段存在时继续转发，字段不存在时省略。

## 5. 修复内容

### 5.1 后端兼容 `ToolEntry` 可选字段

文件：`api/streaming.py`

修复后先构造基础注册参数：

```python
register_kwargs = {
    "name": entry.name,
    "toolset": entry.toolset,
    "schema": entry.schema,
    "handler": _profile_scoped_cronjob_handler,
    "check_fn": entry.check_fn,
    "requires_env": entry.requires_env,
    "is_async": entry.is_async,
    "description": entry.description,
    "emoji": entry.emoji,
    "max_result_size_chars": entry.max_result_size_chars,
}
if hasattr(entry, "dynamic_schema_overrides"):
    register_kwargs["dynamic_schema_overrides"] = entry.dynamic_schema_overrides
registry.register(**register_kwargs)
```

效果：

- 新版 `ToolEntry` 缺字段：不会读取不存在属性，Chat 主链路不中断。
- 旧版 `ToolEntry` 带字段：继续转发动态 schema 元数据。
- cronjob profile wrapper 的 handler、contextvar、线程池 context copy 行为不变。

### 5.2 新增回归测试

文件：`tests/test_scheduled_jobs_profile_isolation.py`

新增测试：

```python
def test_streaming_cronjob_wrapper_tolerates_missing_dynamic_schema_overrides(monkeypatch):
    ...
```

验证点：

- 模拟一个没有 `dynamic_schema_overrides` 属性的 `Entry`。
- 调用 `_install_streaming_cronjob_profile_wrapper()` 不抛异常。
- `registry.register()` 收到的 kwargs 不包含 `dynamic_schema_overrides`。
- 包装后的 handler 仍然可以正常调用原始 handler。

## 6. 线上人工日志排查步骤

当线上再次出现 Chat 发不出回答、页面提示 provider/runtime 异常时，可按以下顺序排查。

### 6.1 先确认 WebUI 服务状态

```bash
./ctl.sh status
curl -sS http://127.0.0.1:8787/health
```

预期：

```json
{"status":"ok"}
```

如果 health 不通，优先排查进程和端口，不进入模型链路排查。

### 6.2 查看 WebUI 后端日志

```bash
./ctl.sh logs --lines 300
```

或直接读取默认日志：

```bash
tail -n 300 ~/.hermes/webui.log
```

重点检索：

```bash
grep -n "dynamic_schema_overrides\\|ToolEntry\\|AttributeError\\|streaming cronjob wrapper" ~/.hermes/webui.log
```

若看到：

```text
'ToolEntry' object has no attribute 'dynamic_schema_overrides'
```

说明故障发生在 WebUI streaming 启动阶段的工具注册兼容层，不应优先判断为模型不可用。

### 6.3 区分模型故障与工具注册故障

工具注册故障特征：

- 报错在模型真正返回 token 前发生。
- 日志中有 Python `AttributeError`。
- 错误字段指向 `ToolEntry.dynamic_schema_overrides`。
- 更换模型可能仍失败，因为故障点在 agent run 初始化阶段。

模型连通性故障特征：

- 日志显示 provider HTTP 请求失败、超时、401、403、429、5xx。
- 错误通常包含 provider/base_url/model/request id 等信息。
- 不会出现 `ToolEntry` 属性缺失。

### 6.4 验证修复是否已上线

在服务器代码目录执行：

```bash
git log -1 --oneline
git show --name-only --format=medium HEAD
```

确认包含提交：

```text
d6d65196 fix(streaming): 兼容缺少 dynamic_schema_overrides 的 ToolEntry
```

并确认文件包含兼容分支：

```bash
grep -n "hasattr(entry, \"dynamic_schema_overrides\")" api/streaming.py
```

### 6.5 线上冒烟验证

1. 登录 WebUI。
2. 打开 Chat 页面。
3. 选择线上默认模型或 `qwen3.6-27b`。
4. 新建会话并发送一个短问题，例如“用一句话回复当前系统是否可用”。
5. 观察页面是否开始流式输出。
6. 后端日志不应再出现 `ToolEntry.dynamic_schema_overrides` 的 `AttributeError`。

## 7. 验证结果

本地定向测试：

```bash
./scripts/test.sh tests/test_scheduled_jobs_profile_isolation.py
```

结果：

```text
13 passed in 3.94s
```

diff 检查：

```bash
git diff --check
```

结果：通过，无空白错误。

提交记录：

```text
d6d65196 fix(streaming): 兼容缺少 dynamic_schema_overrides 的 ToolEntry
```

## 8. 风险与回滚

风险评估：

- 代码只改变 cronjob wrapper 注册参数构造方式，不改 SSE 协议、不改 agent 执行主流程、不改前端渲染。
- 字段存在时继续传递，字段不存在时省略，属于向前/向后兼容修复。
- 对 profile 隔离逻辑的原有测试仍然通过。

回滚方案：

1. 如果上线后出现新的工具注册异常，先保留日志和当前 commit。
2. 临时回滚 `d6d65196`：

   ```bash
   git revert d6d65196
   ```

3. 重启 WebUI：

   ```bash
   ./ctl.sh restart
   ```

4. 若回滚后再次出现原始 `ToolEntry.dynamic_schema_overrides` 缺字段错误，说明必须恢复本兼容修复，继续排查新的异常是否来自其它字段或 `registry.register()` 签名变化。

## 9. 后续建议

1. 对 WebUI 与 Hermes Agent 的工具注册边界增加更完整的兼容层，避免直接假设 agent 内部 dataclass 字段稳定。
2. 后续升级 Hermes Agent 前，在预发环境执行 Chat 冒烟测试，覆盖至少一个常规模型和一个本地/自定义模型。
3. 对 `_install_streaming_cronjob_profile_wrapper()` 增加更多字段兼容测试，尤其是 `emoji`、`max_result_size_chars`、`requires_env` 等注册元数据。
4. 在线上日志告警中把 `ToolEntry` / `AttributeError` 归类为“运行时兼容错误”，与 provider 网络错误分开处理。
