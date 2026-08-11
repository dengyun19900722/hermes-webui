# 自定义 Provider 配置 UI 设计文档

**版本：** v1.0
**日期：** 2026-07-16
**状态：** 已实现（v1.0）

---

## 1. 概述

### 1.1 背景

当前 Hermes WebUI 已经有相当成熟的 Provider / Custom 模型支持：

- 27 个内置 Provider
- 25 个 API key 环境变量映射 + 6 个 OAuth-only Provider
- Plugin 自动发现（`plugins/model-providers/`）
- Onboarding 流程、Provider 卡片、Profile 表单、Aux 高级覆盖、Self-hosted Wizard
- `custom_providers[]` schema 已存在于 `config.yaml`，但**前端 UI 无入口**，必须手编 yaml

**缺失点**：用户无法在 WebUI 内添加 / 修改 / 删除自定义 OpenAI-compatible 中转。技术用户（尤其离线场景）希望"填 baseurl+apikey+modelid 就能用"，但必须手工编辑 yaml，门槛高。

### 1.2 目标

让技术用户（尤其离线场景）能在 WebUI 内 **CRUD** 自定义 OpenAI-compatible provider，所有 profile 自动生效。

### 1.3 设计原则

- **复用现有**：完全复用 `custom_providers[]` schema、`_buildProviderCard` 模式、`/api/onboarding/probe` 流程
- **存储一致**：写 `config.yaml`（含 `custom_providers[].api_key` literal），不引入新数据库（不写 `.env`，保留内置 provider 使用）
- **拒绝回显 key**：API key 只通过 `has_key: bool` 暴露，永不回 value
- **离线优先**：Custom 区放在 Providers 面板**最顶部**（用户主用途）
- **一次添加，全 profile 生效**：Add/Edit/Delete/Set-default 全部广播
- **YAGNI**：不引入 model-level overrides、OAuth、Plugin 改动

### 1.4 不在范围内

- ❌ 不引入 model-level config（每个 model 单独 base_url/api_key）
- ❌ 不改 built-in provider 的 base_url/apikey（用现有 profile 流程）
- ❌ 不动 plugin discovery
- ❌ 不加 OAuth 流程
- ❌ 不写新数据库表

---

## 2. 架构

### 2.1 存储

```
~/.hermes/
├── config.yaml                    # 每个 profile 一份
│   └── custom_providers:          # 已有 schema，新功能新增条目
│       - name: "My OpenAI 中转"
│         slug: "my-openai"
│         base_url: "https://relay.example.com/v1"
│         api_key: "sk-xxxxx"          # literal（不复用 .env，参见 api/providers.py:1199-1208）
│         models: ["gpt-4o", "gpt-4o-mini"]
└── .env                            # 仅用于内置 provider（如 OPENROUTER_API_KEY），custom 不写
```

### 2.2 前后端模块分工

#### 前端（不引入新文件，复用现有面板代码）

| 现有锚点 | 文件 | 行 | 改动 |
|---|---|---|---|
| `loadProvidersPanel()` | `static/panels.js` | 10550 | 入口改写：custom 置顶 + built-in 折叠 |
| `_buildProviderCard(p)` | `static/panels.js` | 10971 | 新增变体 `_buildCustomProviderCard(item)` |
| `_saveSelfHostedProvider()` | `static/panels.js` | 11418 | 新增 `_saveCustomProvider(payload, mode)` |
| `_testSelfHostedConnection()` | `static/panels.js` | 11356 | 新增 `_probeCustomProvider(payload)` |
| Composer model dropdown | `static/ui.js` | 4011 | 新增：下拉底部追加「➕ 添加自定义模型…」入口；点击触发 mini modal（见 §2.8） |
| `_populateProfileFormModelSelect()` | `static/panels.js` | 7220 | 无需改（`data-provider="custom:<slug>"` 已能筛） |

#### 后端（最小改动）

**3 个新 endpoint 落 `api/routes.py`，1 个新模块抽业务**：

| 路径 | 方法 | 作用 |
|---|---|---|
| `/api/custom_providers` | GET | 列出所有 custom provider + 状态（key 仅 `has_key` 不回 value） |
| `/api/custom_providers` | POST | Add/Edit/Delete（`body.action = "upsert" \| "delete"`） |
| `/api/custom_providers/probe_models` | POST | Probe `<baseurl>/v1/models` 返回候选（**不写盘**） |
| `/api/custom_providers/set_default` | POST | 「⭐ 设为默认」：写所有 profile 的 `model.provider` + `model.default` |

新增模块 `api/custom_providers.py`，业务逻辑抽出来。

### 2.3 数据流（Add 完整时序）

```
User 点 +Add → UI _openAddCustomModal()
... (填字段) ...
User 点 Fetch models → POST /api/custom_providers/probe_models
  → _fetch_models() 调 GET {baseurl}/models (4s timeout)
  ← {ok, models[], latency_ms, error?}
UI 显示候选 chips

User 点 Probe 保存
  → POST /api/custom_providers {action: upsert, provider: {...}}
    ├─ _validate()             # slug/name/models/base_url/slug-unique
    ├─ _probe(base_url, key)   # 失败则 400 + reason（除非 skip_probe=true）
    ├─ for home in all_profile_homes():
    │     load → upsert custom_providers[].{name, slug, base_url,
    │                                       api_key (literal 或空),
    │                                       models[]} → save_yaml
    │     collect failures
    ├─ invalidate_models_cache() + reload_config()
  ← {ok, provider, models_count, has_key, failed_profiles[]}
UI 重渲染面板 + toast/banner
```

### 2.4 Probe / Fetch-models endpoint（独立 POST，不写盘）

- `POST /api/custom_providers/probe_models`
- body: `{base_url, api_key}`
- 内部：复用 `probe_models_for_url(base_url)`（`api/onboarding.py:362`）
- 4s timeout
- 响应：`{ok: bool, models: [...], latency_ms, error?}`
- **不**写盘，**不**依赖 .env

### 2.5 Delete 流程

```
POST /api/custom_providers { action: "delete", slug: "my-openai" }
  │
  ├─ for home in all_profile_homes():
  │     load → 移除 custom_providers[] 里 slug 匹配条目 → save
  │
  ├─ 清 custom_providers[].api_key （key 写在 config.yaml 里，删除条目即一并清除，**不**涉及 .env）
  │
  ├─ invalidate_models_cache() 等
  │
  ◄ { ok, failed_profiles[] }
```

### 2.6 Set-default 流程

```
POST /api/custom_providers/set_default { slug: "my-openai", model: "gpt-4o" }
  │
  ├─ 校验: slug 存在于 custom_providers[]；model 属于该 provider 的 models[]
  ├─ for home in all_profile_homes():
  │     cfg["model"] = {
  │       "provider":  "custom:my-openai",
  │       "default":   "gpt-4o"
  │     } → save_yaml
  ├─ reload_config() + invalidate
  ◄ { ok, failed_profiles[] }
```

不影响 `model.base_url`（custom provider 的 base_url 走 `custom_providers[].base_url`，不写全局 `model.base_url`）。

### 2.7 Profile scope 行为

| 写操作 | 实际生效范围 |
|---|---|
| Add / Edit / Delete provider | 当前 + 所有 profile（即时广播） |
| Set default | 所有 profile（即时广播） |
| Probe / Fetch-models | 仅内存（不写盘） |

不暴露「仅当前 / 全部」切换——已确认默认全部，未来要扩展加 radio。

### 2.8 Composer 快捷入口（Quick-add）

**入口**：Composer 模型下拉（`static/ui.js:4011` 附近）底部追加一行：

```
─────────────────────────
➕ 添加自定义模型…
```

**触发**：点击 ➕ → 打开 mini modal（不是 Settings Providers 面板的全量 modal）。

**Mini modal 字段**（极简版）：

| 字段 | 必填 | 说明 |
|---|---|---|
| 显示名 | 否 | 留空则按 baseurl 自动派生（host 段） |
| Base URL | **是** | http(s):// 开头，自动 strip 尾部 `/` |
| API Key | 否 | 留空表示无 key 中转（公开端点） |

**Model id 探测**：mini modal 打开后，输入 baseurl debounce 300ms → 自动调 `/api/custom_providers/probe_models` 拉候选 models → 填进下拉让用户选（或默认第一个）。探测失败（4s 超时/网络错误）→ 用 `"default"` 作为唯一 model id 占位。

**「添加并切换」语义**：

```
User 填 baseurl + (可选) apikey + (可选) name
点 "添加并切换"
  → POST /api/custom_providers {action: upsert, provider: {name, slug, base_url, api_key, models}}
    # 与 §2.3 Add 走完全相同接口 + 校验 + 广播 + invalidate
    # slug 自动从 name 派生；name 留空时从 baseurl host 派生
  ← {ok, provider, models_count, has_key, failed_profiles[]}
  ├─ 关闭 mini modal
  ├─ 刷新 composer 下拉（GET /api/custom_providers + GET /api/models）
  ├─ 自动选中刚加 provider 的 models[0]
  ├─ 顶部 toast: "已添加 <name>，下一次发送使用"
```

**与 Settings Providers 面板的关系**：

- mini modal 创建的条目**持久化到 config.yaml（广播所有 profile）**
- 与 Providers 面板的「+ Add custom provider」**写入完全相同的 `custom_providers[]` 条目**
- 用户后续可在 Settings Providers 面板里编辑/删除/设为默认（同一份数据）
- mini modal 是「快速入口」，不是「临时机制」—— 数据生命周期与全量表单一致

**与现有下拉行为的差异**：

- 现有 composer 下拉刷新策略不变（依赖 `/api/models`）
- 「➕」一行在所有 custom provider 已存在/不存在时都显示（始终可见）
- 点击 ➕ 不关闭下拉，直接打开 mini modal

**i18n 新增键**（在 §4.1 附录 A 增加 4 条）：

```js
custom_provider_composer_quickadd_label: '➕ 添加自定义模型…',
custom_provider_quickadd_title: '快速添加自定义模型',
custom_provider_quickadd_subtitle: '保存后会出现在下拉里，可后续在 Providers 面板编辑',
custom_provider_quickadd_added_toast: (name) => `已添加 ${name}，下一次发送使用`,
```

---

## 3. 错误处理

### 3.1 输入校验（前端先拦 → 后端兜底）

| 错误 | 前端阻断 | 后端兜底 | UI 表现 |
|---|---|---|---|
| `name` 空 | ✅ | 400 `name_required` | 红框 + 提交禁用 |
| `slug` 空 / 非法字符 | ✅ regex `^[a-z0-9._-]{1,64}$` | 400 `slug_invalid` | 红框 |
| `slug` 冲突 (与现有 built-in / 其他 custom) | ✅ 实时查 | 400 `slug_taken` | 红框 + "已存在，改一个" |
| `base_url` 非 http(s):// | ✅ | 400 `base_url_invalid` | 红框 |
| `models` 空 | ✅ | 400 `models_empty` | 灰化保存 |
| `models` 含重复 | ✅ 去重 + 提示 | 同上 | chips 高亮 |

校验函数返回**单错误**（简单展示）+ **多错误列表**（首次提交时全部展示）。

### 3.2 Probe 失败

| 场景 | 探测响应 | UI 表现 |
|---|---|---|
| 网络不可达 / DNS 失败 | `{ok:false, error:'unreachable'}` | 模态底部红 banner：无法连接 `<baseurl>` |
| Timeout (>4s) | `{ok:false, error:'timeout', latency_ms:4000}` | banner：连接超时 |
| HTTP 401 / 403 | `{ok:false, error:'auth_failed', status:401}` | banner：API key 无效或被拒 |
| HTTP 404 | `{ok:false, error:'not_found'}` | banner：`<baseurl>/models` 不存在 |
| HTTP 5xx | `{ok:false, error:'upstream_error', status:502}` | banner：上游服务异常 |
| 返回非 JSON / 非法格式 | `{ok:false, error:'invalid_response'}` | banner：返回格式无法识别 |
| Probe 失败 + 用户点 "直接保存" | skip_probe=true 保存 | 警告 toast：「未验证连接，已保存」 |

UI 行为：「**Probe 保存**」按钮：探测失败 → 模态不关闭，让用户改 base_url/key 后重试。「**直接保存**」按钮：跳过探测，强存 → 适用于已知靠谱的中转场景。

### 3.3 写盘失败（per-profile 收集，**不阻断**）

```
POST /api/custom_providers { action: "upsert", ... }
  │
  ├─ for home in all_profile_homes():
  │     try:
  │       load → upsert → save_yaml
  │     except PermissionError as e:
  │       failed_profiles.append({home, error:'permission_denied', detail:str(e)})
  │     except YAMLError as e:
  │       failed_profiles.append({home, error:'yaml_corrupt', detail:str(e)})
  │     except OSError as e:
  │       failed_profiles.append({home, error:'io_error', detail:str(e)})
  │
  ◄ HTTP 200 即使部分失败：
    {
      ok: <true if all succeeded else false>,
      provider: {slug, name, ...},
      models_count: 2,
      has_key: true,
      failed_profiles: [
        {profile: "work", home: "/home/u/.hermes/profiles/work",
         error: "permission_denied", detail: "..."}
      ],
      succeeded_count: 4,
      total_count: 5
    }
```

**UI 表现**：

- 全部成功 → green toast "已保存到 5/5 个 profile"
- 部分失败 → **不阻塞关闭模态**，黄色 banner："已保存到 4/5，1 个失败" + 「查看详情」折叠面板 + 「重试失败的 profile」按钮
- 全部失败 → **不关闭模态**，红色 banner："保存失败，请重试或联系管理员"
- 失败详情提供「复制失败 profile home 路径」按钮，引导用户 chmod

### 3.4 Config.yaml 写失败

- API key 字面量写在 `config.yaml → custom_providers[].api_key`（**不**写 .env，避免与内置 provider env-var 流程冲突）
- yaml 写失败通过 §3.3 per-profile 收集，单 profile 失败不影响其他
- `~/.hermes/.env` **不**被此功能触碰；权限 0600 约束沿用既有流程（如果新触发 .env 才校验）

**安全细节**：

- API key 在 config.yaml 与现有 `providers.<id>.api_key` 同安全等级（gitignore + 文件权限 0600 沿用）
- 服务端所有 GET 响应只回 `has_key: bool`，绝不回 key 值
- 日志记录时按现有 `api/providers.py` redactor 流程脱敏

### 3.5 并发 / 竞态

| 竞态 | 防护 |
|---|---|
| 两个 tab 同时 add 同一个 slug | 写时拿文件锁 `/tmp/hermes-cfg.lock`（已有，写入 `_save_yaml_config`），冲突 → `lock_timeout` |
| Probe 进行中点取消 | `AbortController` 中断 fetch，后端丢弃响应 |
| Cache stale | 写后 `invalidate_models_cache()` + `reload_config()` 兜底 |
| 浏览器断网 | fetch 超时统一 10s；toast「网络断开」 |

### 3.6 边界与 corner case

| 情况 | 处理 |
|---|---|
| 用户改 slug 但 key 留空 | key 不动，.env 不写 |
| 删除唯一 custom provider 后 profile 没有 model | fallback 到默认 anthropic + 黄 banner |
| slug 与 built-in 冲突（"anthropic"） | 阻断 |
| 用户把 `auth.json`（oauth 凭据池）路径误填进 base_url | base_url 校验只允许 http(s):// 开头 |
| 用户用 `custom:` 前缀填 slug | 自动剥前缀再存，内部 slug 不带 `custom:` |
| 自定义 provider 名带 emoji / 中文 | 允许（前端直接渲染） |
| 一个 profile 已被外部锁住读 | yaml 读异常 → 失败计入 `failed_profiles[]` |
| 用户在 Plugin provider 里写了同名 slug | `plugin_model_provider_ids()` 检查 → 400 `slug_collides_with_plugin` |

---

## 4. i18n + 状态管理 + 边界细节

### 4.1 i18n 键（新增到 `static/i18n.js` `LOCALES.zh` 和 `LOCALES.en`）

完整 39 键（中英平行，详见附录 A）：

```js
// zh-CN
custom_providers_title: '自定义中转 / 代理',
custom_providers_subtitle: '在所有 profile 里同时生效',
custom_providers_add_btn: '+ 添加自定义 provider',
custom_providers_empty: '暂无自定义 provider，点击右上角添加',
custom_provider_card_probe: '探测',
custom_provider_card_edit: '编辑',
custom_provider_card_delete: '删除',
custom_provider_card_set_default: '⭐ 设为默认',
custom_provider_field_base_url: 'Base URL',
custom_provider_field_api_key: 'API Key',
custom_provider_field_models: 'Models',
custom_provider_field_api_key_hint: '已配置。留空保留，填写则覆盖。',
custom_provider_btn_add_model: '+ 添加 model id',
custom_provider_btn_fetch_models: '从 /v1/models 拉取',
custom_provider_btn_probe_save: '探测后保存',
custom_provider_btn_save_direct: '直接保存',
custom_provider_save_ok: (s, t) => `已保存到 ${s}/${t} 个 profile`,
custom_provider_probe_unreachable: (url) => `无法连接 ${url}`,
custom_provider_probe_timeout: '连接超时（>4s）',
custom_provider_probe_auth_failed: 'API key 无效或被拒绝',
custom_provider_probe_not_found: (url) => `${url}/models 不存在`,
custom_provider_probe_save_skip: '未验证连接，已保存',
custom_provider_set_default_ok: (m) => `已将 ${m} 设为默认模型`,
custom_provider_delete_confirm: (name) => `确认删除 "${name}"？将从所有 profile 移除`,
custom_provider_slug_invalid: 'Slug 只能 a-z 0-9 . _ -，长度 1-64',
custom_provider_slug_taken: 'Slug 已被使用',
custom_provider_slug_collide_builtin: '不能与内置 provider 重名',
custom_provider_models_empty: '至少添加 1 个 model id',
custom_provider_retry_failed_btn: '重试失败的 profile',
custom_provider_lock_timeout: '配置正被占用，请重试',
// ... 完整对照表见附录 A（i18n 全表）
```

每条都通过 `t('custom_provider_xxx')` 调用；现有 inline English fallback 模式保留。

### 4.2 状态管理

| 状态 | 位置 | 时机 |
|---|---|---|
| `_customProviders[]` | UI 全局 | Add/Edit/Delete 后强制 reload；面板首次进入 reload |
| `_currentEditingSlug` | modal 局部 | 打开模态时设，关闭清 |
| `_probedModelsCache` | modal 局部 | base_url+key 哈希后存，同组合不重复 probe |
| `modelState.default_*` | 既有全局 | set-default 后 reload `/api/profile/active` |

### 4.3 UI 边界细节

| 情况 | 处理 |
|---|---|
| Modal 打开后改 base_url | 清 probed cache + 提示"已变，请重新拉取" |
| 删除 default 绑定的 provider | confirm："删除后新会话将退回到 fallback 默认" |
| Edit 模式 slug 字段 | **禁用**（slug 是主键，不可改） |
| base_url 含尾部 `/` | 自动 strip |
| models 含空格 | 自动 trim |
| 用户粘贴逗号分隔 model ids | 解析为 chips |
| 重复点 Fetch models | `AbortController` 取消上一次 |
| Modal 里按 ESC | 关闭（不保存） |
| 双重提交防护 | 第一点击后 disable 按钮 |
| Modal 高度溢出 | scrollable + sticky 底部按钮条 |
| 外部直接改 yaml | 打开面板时 `GET /api/custom_providers` 重新拉取 |

### 4.4 跨组件影响

| 触发 | 级联 |
|---|---|
| Custom provider 改 | Composer 下拉「Custom」分组刷新 |
| Set default 之后 | composer 当前选项变 + profile badge 变 |
| Delete 之后 | composer 该 provider 所有 model 灰化（"已删除"）直到下次 reload |
| Profile switch | modal 自动关闭，状态 reset |
| Logout | 清 modal 状态 |

### 4.5 RBAC 钩子（参考 `4b91bce6 docs: add RBAC`）

留 3 个权限点 hook：
- `custom_providers:read`
- `custom_providers:write`
- `custom_providers:set_default`

**降级策略**：RBAC 未落地前全部用户都有读写 + set_default（不挡），代码留 hook；RBAC 落地后用一行 import 接通。

### 4.6 Profile 切换副作用

| 场景 | 行为 |
|---|---|
| 当前 A，编辑 provider | 模态显示 "修改会应用到所有 profile"，保存即广播 |
| 切到 B | 自动关闭模态（防脏态），重 reload 列表 |
| B profile 看「⭐ 设为默认」 | 默认所有 profile 都显示（行为一致） |

### 4.7 数据迁移

无现有数据需迁移——`custom_providers[]` schema 已存在，仅是 UI 暴露它。

唯一补字段：`slug`。现有手写 yaml 无 slug 的条目 → 加载时按 `_custom_provider_slug_from_name(name)` 自动派生并写回（透明迁移）。

---

## 5. 测试

### 5.1 分层

```
单元 (pytest)            集成 (pytest + test_server)         端到端 (e2e)
─────────────────       ────────────────────────────        ──────────────
api 业务函数             HTTP endpoint 完整请求               (本项目暂不写)
输入校验                 写盘广播到多 profile
probe 纯函数             .env / config.yaml 实际改动
slug 派生 / 校验         部分失败 + failed_profiles 回流
                        /api/models 下拉包含 custom
```

### 5.2 用例清单

#### 单元 (api/custom_providers.py 纯函数)

| 文件 | 用例 | 验证 |
|---|---|---|
| `tests/test_custom_providers_slug.py` | `test_slug_from_name_basic` | "My OpenAI" → "my-openai" |
| | `test_slug_strip_invalid_chars` | "relay/@host" → "relay-host" |
| | `test_slug_trim_to_64` | 超长截断 |
| | `test_slug_collides_builtin` | "anthropic" → ValueError |
| | `test_slug_collides_plugin` | "opencode-go" → ValueError |
| | `test_slug_required` | 空 → ValueError |
| `tests/test_custom_providers_validation.py` | `test_validate_missing_name` | 400 |
| | `test_validate_missing_base_url` | 400 |
| | `test_validate_models_empty` | 400 |
| | `test_validate_models_duplicates` | 400 |
| | `test_validate_base_url_must_http` | "ftp://..." → 400 |
| | `test_validate_base_url_no_trailing_slash` | 自动归一化 |
| `tests/test_custom_providers_probe.py` | `test_probe_ok` | mock `{data:[{id:'a'},{id:'b'}]}` → ok |
| | `test_probe_timeout` | 5s 延迟 → error:'timeout' |
| | `test_probe_401` | error:'auth_failed' |
| | `test_probe_404` | error:'not_found' |
| | `test_probe_invalid_json` | error:'invalid_response' |
| | `test_probe_data_id_or_model_field` | 同时支持 `id` 和 `model` 字段 |
| | `test_probe_dedupes_duplicate_ids` | [a,a,b] → [a,b] |

#### 集成（HTTP + 多 profile fixture）

| 文件 | 用例 | 验证 |
|---|---|---|
| `tests/test_custom_providers_crud.py` | `test_get_empty` | `[]` |
| | `test_post_upsert_then_get` | 写一项 → 读出一项 |
| | `test_post_upsert_overwrites_same_slug` | upsert 不重复 |
| | `test_post_delete` | 200 + 列表为空 |
| | `test_post_delete_removes_env_when_unreferenced` | .env 行消失 |
| | `test_post_delete_keeps_env_when_referenced` | 别人在用，保留 |
| `tests/test_custom_providers_broadcast.py` | `test_writes_all_profiles_yaml` | 5 mock home，5 个 yaml 都包含 |
| | `test_partial_failure_returns_failed_profiles` | 1 chmod 000 → 4 成功 + 1 失败 |
| | `test_failed_yaml_lists_per_profile` | failed_profiles[{profile, error, detail}] |
| | `test_no_partial_commit_on_env_failure` | .env 失败 → 全 yaml 都不写 |
| `tests/test_custom_providers_set_default.py` | `test_set_default_writes_model_section` | 所有 profile `model.provider/custom:slug` + `model.default` |
| | `test_set_default_with_unknown_slug` | 400 |
| | `test_set_default_with_unknown_model` | 400 |
| `tests/test_custom_providers_models_integration.py` | `test_models_dropdown_includes_custom` | `/api/models` 返回 custom 分组 |
| | `test_get_providers_includes_custom` | `/api/providers` 返回 custom 条目 |
| `tests/test_custom_providers_concurrency.py` | `test_lock_timeout_under_parallel` | 2 个 POST 并发 → 1 成功 1 lock_timeout |
| | `test_atomic_yaml_write` | 写时中断 → 不留下半截 yaml |
| `tests/test_custom_providers_quickadd.py` | `test_quickadd_minimal_body_creates_entry` | 仅 baseurl 也能成功（name/models 派生） |
| | `test_quickadd_name_optional_derived_from_baseurl_host` | baseurl 派生 display_name + slug |
| | `test_quickadd_models_probed_on_200` | 探测成功 → 填 models[] |
| | `test_quickadd_models_default_placeholder_on_probe_failure` | 探测失败 → models=["default"] |
| | `test_quickadd_persists_to_all_profiles` | 与全量表单一致广播 |
| | `test_quickadd_visible_in_providers_panel_after` | mini 创建后 Settings Providers 面板立即可见 |
| | `test_quickadd_auto_selects_first_model_in_composer` | 返回 models[0] |

#### 安全（`tests/test_custom_providers_security.py`）

| 用例 | 验证 |
|---|---|
| `test_get_response_never_includes_api_key_value` | 响应 JSON 递归检查无 key value |
| `test_logs_redact_api_key` | logger.info 不打印 `sk-...` |
| `test_env_file_mode_0600` | 写完后 `os.stat().st_mode & 0o777 == 0o600` |
| `test_yaml_write_atomic` | 临时文件 + rename，模拟中途崩溃 |
| `test_block_localhost_base_url` | "http://127.0.0.1:11434/v1" → 需 `confirm=true` 才能保存 |

### 5.3 测试基础设施

- **复用 conftest** `test_server` fixture → 集成测试
- **纯函数**：直接 import + 调，无 fixture → 快（毫秒级）
- **mock 模式**：
  - HTTP probe：`responses` 库拦截
  - 文件 I/O：`tmp_path` + `monkeypatch.setattr(home, ...)`
  - 多 profile：构造 N 个 `cfg = {"config.yaml" minimal}` 临时目录
- **不写 JS unit**（项目无 jsdom/vitest 配置）
- **不写真实外网 probe**（全部 mock）

### 5.4 不在测试范围

- ❌ OAuth provider（custom 永远 static key）
- ❌ Plugin discovery 冲突（plugin 体系自带测试）
- ❌ 主题色 / 字号个性化（已有 visual_test 覆盖）
- ❌ i18n 翻译完整性（仅 smoke 检查键存在）
- ❌ e2e Playwright/Cypress（项目未使用）

### 5.5 手动验证清单（部署后人工跑）

- [ ] 添加：填 baseurl+key → Probe 保存 → 5/5 profile 都生效
- [ ] 探测失败：填不存在 baseurl → red banner，不关模态
- [ ] Fetch models：成功 / 失败 / 4s timeout 三种
- [ ] 编辑：改名 / 改 baseurl / 改 models / 改 key（覆盖）/ 改 key（留空）
- [ ] 删除：confirm 弹窗 + .env 清理（无引用时）
- [ ] Set default：composer 当前选项变 + profile badge 更新
- [ ] Slug 冲突：填 "anthropic" → 被拒
- [ ] 反复刷新页面：custom 区数据持久
- [ ] **离线环境**：仅 custom provider，所有 built-in 折叠，仍可用
- [ ] **Composer ➕ 快捷入口**：composer 下拉底部「➕ 添加自定义模型…」可见
- [ ] **Mini modal 添加**：仅 baseurl + 可选 apikey → 添加成功 → 下拉自动选中
- [ ] **Mini modal 添加后去面板**：在 Settings Providers 面板能看到刚加的条目，可编辑
- [ ] **Mini modal 探测失败**：无 `/v1/models` 时仍能用（占位 model）

### 5.6 性能 / 稳定性

- probe timeout 4s 单测，不阻塞后续操作
- broadcast 写 N profile：N≤10 实测 <100ms（个人用户），可接受
- 无 multi-profile 时（仅 default）正常处理：fallback 到仅写 default
- custom provider 数量 >50 暂不优化（实际场景 N≤10）

---

## 6. 关键决策记录

| 决策 | 替代方案 | 选择理由 |
|---|---|---|
| Custom 区置顶（不是底部） | 底部折叠区 | 离线场景下自定义 provider 是主路径 |
| `api_key` literal 存 yaml，不写 .env | `${ENV_VAR}` 占位符或复用 .env | custom provider 无 env_var 映射（`api/providers.py:1199-1208`），literal 最简单；永不回显 |
| Add 时广播所有 profile | 仅当前 profile | 用户期望"一次添加，处处可用" |
| 「⭐ 设为默认」动作 | 不暴露全局默认设置 | 离线场景下常见"设置一次永久生效" |
| Endpoint 路径 `/api/custom_providers` | `/api/providers/custom` | 用户确认，与 `_PROVIDER_*` 命名风格区分更清晰 |
| Probe 复用 `onboarding.py:362` | 新写 | 不重新造 |
| 不引入 model-level overrides（方案 C） | 重型方案 | 与用户回答不匹配 |
| i18n 39 键 | 减少到 10 | 体验一致性 + 复用现有 inline fallback 模式 |
| 写盘失败部分成功（不阻断） | 全成功或全失败 | 容错更好，UI 引导用户处理 |
| Probe 失败允许"直接保存" | 必须 probe 才保存 | 已知靠谱中转场景 |
| RBAC 钩子留 hook | 现在就接全 RBAC | 不阻塞当前 PR |
| 不写前端 JS unit / e2e | 全写 | 项目无基础设施，不重起 |
| Edit 模式 slug 禁用 | 允许改 slug | slug 是主键，改名风险大 |
| Composer ➕ 快捷入口（mini modal） | 仅 Settings Providers 面板 | 减少操作路径，「点下拉选不到 → 加一个」一步到位；持久化与全量表单同源 |

---

## 7. 参考

### 现有代码锚点

- `api/providers.py:1170` `_provider_has_key()` — api key 检测六层优先级
- `api/onboarding.py:362` `probe_models_for_url()` — 现成 probe，可复用
- `api/onboarding.py:1048` `apply_self_hosted_setup()` — 现有 self-hosted 写盘流程
- `api/routes.py:14295` `POST /api/providers` — 现有 provider key 设置模式
- `api/routes.py:14316` `POST /api/providers/self-hosted` — 现有 self-hosted 模式
- `api/config.py:1359` `_custom_provider_slug_from_name()` — slug 派生
- `api/config.py:1221` `_PROVIDER_ALIASES` — 用户友好名 → canonical slug
- `api/config.py:1651+` `_PROVIDER_MODELS` — 每个 provider 硬编码 fallback 模型目录
- `static/panels.js:10550` `loadProvidersPanel()` — 入口改写位置
- `static/panels.js:10971` `_buildProviderCard(p)` — 卡片模式可复用
- `static/panels.js:11356` `_testSelfHostedConnection()` — probe-then-save 流程
- `static/ui.js:12002` `_auxAdvancedInputHtml()` — base_url/api_key 字段 UI 模式
- `static/onboarding.js:11-40` — onboarding form 字段名

### 测试参考

- `tests/test_stale_stream_cleanup.py` — mock 模式（hot path）
- `tests/test_issue1106_custom_providers_models.py` — custom_providers 现有测试
- `tests/test_provider_management.py` — provider 端到端测试模式
- `tests/test_auxiliary_models_settings.py` — aux model 测试模式

### 历史 commit

- `4b91bce6` docs: add RBAC permission system design spec（最近 RBAC 设计参考）
- `c2e9277c` release: reuse the rich model picker in Preferences (#5502)

---

## 附录 A：i18n 全表

完整中英对照键（实现时按此填入 `LOCALES`）：

| 键 | zh-CN | en |
|---|---|---|
| `custom_providers_title` | 自定义中转 / 代理 | Custom providers / relays |
| `custom_providers_subtitle` | 在所有 profile 里同时生效 | Apply to all profiles |
| `custom_providers_add_btn` | + 添加自定义 provider | + Add custom provider |
| `custom_providers_empty` | 暂无自定义 provider，点击右上角添加 | No custom providers yet. Click + to add |
| `custom_provider_card_probe` | 探测 | Probe |
| `custom_provider_card_edit` | 编辑 | Edit |
| `custom_provider_card_delete` | 删除 | Delete |
| `custom_provider_card_set_default` | ⭐ 设为默认 | ⭐ Set as default |
| `custom_provider_field_name` | 显示名 | Display name |
| `custom_provider_field_slug` | Slug | Slug |
| `custom_provider_field_base_url` | Base URL | Base URL |
| `custom_provider_field_api_key` | API Key | API Key |
| `custom_provider_field_models` | Models | Models |
| `custom_provider_field_api_key_hint` | 已配置。留空保留，填写则覆盖。 | Configured. Leave blank to keep, fill to overwrite. |
| `custom_provider_btn_add_model` | + 添加 model id | + Add model id |
| `custom_provider_btn_fetch_models` | 从 /v1/models 拉取 | Fetch from /v1/models |
| `custom_provider_btn_probe_save` | 探测后保存 | Probe & Save |
| `custom_provider_btn_save_direct` | 直接保存 | Save directly |
| `custom_provider_save_ok` | 已保存到 N/M 个 profile | Saved to N/M profiles |
| `custom_provider_save_partial` | 部分失败 | Partial failure |
| `custom_provider_save_failed` | 保存失败，请重试 | Save failed, please retry |
| `custom_provider_probe_unreachable` | 无法连接 {url} | Cannot connect to {url} |
| `custom_provider_probe_timeout` | 连接超时（>4s） | Connection timeout (>4s) |
| `custom_provider_probe_auth_failed` | API key 无效或被拒绝 | API key invalid or rejected |
| `custom_provider_probe_not_found` | {url}/models 不存在 | {url}/models not found |
| `custom_provider_probe_invalid_response` | 返回格式无法识别 | Response format unrecognized |
| `custom_provider_probe_save_skip` | 未验证连接，已保存 | Connection not verified, saved anyway |
| `custom_provider_set_default_ok` | 已将 {m} 设为默认模型 | {m} set as default model |
| `custom_provider_delete_confirm` | 确认删除 "{name}"？将从所有 profile 移除 | Delete "{name}" from all profiles? |
| `custom_provider_slug_invalid` | Slug 只能 a-z 0-9 . _ -，长度 1-64 | Slug only a-z 0-9 . _ -, 1-64 chars |
| `custom_provider_slug_taken` | Slug 已被使用 | Slug already used |
| `custom_provider_slug_collide_builtin` | 不能与内置 provider 重名 | Cannot collide with built-in providers |
| `custom_provider_models_empty` | 至少添加 1 个 model id | At least 1 model id required |
| `custom_provider_retry_failed_btn` | 重试失败的 profile | Retry failed profiles |
| `custom_provider_lock_timeout` | 配置正被占用，请重试 | Config busy, please retry |
| `custom_provider_composer_quickadd_label` | ➕ 添加自定义模型… | ➕ Add custom model… |
| `custom_provider_quickadd_title` | 快速添加自定义模型 | Quick add custom model |
| `custom_provider_quickadd_subtitle` | 保存后会出现在下拉里，可后续在 Providers 面板编辑 | Saved entry will appear in dropdown; can be edited in Providers panel |
| `custom_provider_quickadd_added_toast` | 已添加 {name}，下一次发送使用 | {name} added; will be used on next send |

---

**版本历史**

- v1.0 (2026-07-16) 初稿
