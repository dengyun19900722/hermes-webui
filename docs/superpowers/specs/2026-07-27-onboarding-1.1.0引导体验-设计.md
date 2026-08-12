# ZK 运维智能体 1.1.0 — 运维助手快速上手体验优化 设计文档

**版本：** v1.0
**日期：** 2026-07-27
**状态：** 待实现
**目标版本：** ZK 运维智能体 1.1.0
**关联周报：** [[../工作日报/周报/2026-W29 07.20—07.24 周报（ZK运维智能体）]]
**关联需求：** ZKREQ-130（业务线实体关系表）、ZKREQ-131（知识库整理）、ZKREQ-132（巡检诊断技能验证）

---

## 1. 概述

### 1.1 背景

Hermes WebUI 已有完整的"首次部署初始化"流程：`license 激活 → onboarding 向导（系统/工作区/密码/provider）→ setup 路由 → 管理员初始化`。这条流程走完后，新用户进入主应用时面临"功能丰富但不知从哪开始"的认知断层。

ZK 运维智能体 1.1.0 目标：在初次部署完成后到熟练使用之间，提供 4 类**触发式引导页**，覆盖首次用户、新会话、技能发现、实施人员 4 个高摩擦场景。

### 1.2 目标

通过 4 类引导页设计，形成"从第一次使用到熟练使用"的顺滑路径：
- 降低新用户认知成本
- 让新会话用户更快找到入口
- 提升技能发现率与使用率
- 实施人员部署后能 step-by-step 走完使用条件检查，不遗漏关键步骤

### 1.3 设计原则

- **轻量**：引导内容简洁，避免信息过载
- **可引导**：用户可点击进入下一步，不是强制流程
- **可复用**：同一引导框架（`GuidanceManager`）应用于多场景
- **可关闭**：默认开启、可跳过、可后续关闭
- **YAGNI**：不引入新的持久层、不改 onboarding.js 现有 wizard

### 1.4 范围

✅ 包含：
- 4 个引导页 UI（2.4 实施助手 / 2.1 首次使用 / 2.2 会话开始 / 2.3 技能发现）
- `static/guidance.js`（新模块）+ `static/guidance.css`（可选）
- `api/guidance_progress.py`（新模块，仅服务 2.4）
- 1 个新 endpoint 扩展到 `api/skill_usage.py`（catalog）
- i18n key 新增（`guidance_*` 前缀）
- 双重持久化：localStorage（个人引导状态）+ YAML（2.4 实施清单）
- RBAC：2.4 仅 admin/ops 可见

❌ 不包含：
- 修改 `static/onboarding.js`（现有 wizard）
- 修改 license 激活流程
- 修改 RBAC 权限模型（仅消费现有 role 概念）
- PDF 导出（v1.1.0 仅 Markdown；后续版本支持）
- XLSX 导入（v1.1.0 仅 CSV）
- 跨 profile 同步（每个 profile 独立进度）
- 推送通知 / 邮件提醒

---

## 2. 章节重排（用户决策）

按"实施人员是新部署后第一个需要引导的角色"的判断，将原文档 2.4 移到首位：

| 新章节 | 原章节 | 引导页 | 优先级 |
|---|---|---|---|
| **2.1** | 2.4 | 实施助手引导页 ⭐ | P0（最高） |
| **2.2** | 2.1 | 运维助手使用引导页 | P1 |
| **2.3** | 2.2 | 会话开始引导页 | P2 |
| **2.4** | 2.3 | 技能使用引导页 | P3 |

后续章节均按此新顺序编号。

---

## 3. 架构总览

### 3.1 模块布局

```
┌─────────────────────────────────────────────────────────────┐
│  前端 (static/)                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ guidance.js  (新) — 4 类引导页统一调度                │  │
│  │  ├─ GuidanceManager (singleton)                       │  │
│  │  ├─ Page2_1_Implementation   (全屏页)                 │  │
│  │  ├─ Page2_2_FirstUse         (modal)                  │  │
│  │  ├─ Page2_3_NewSession       (内嵌组件)               │  │
│  │  └─ Page2_4_SkillDiscovery   (popover + 内嵌页)       │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ i18n.js — 新增 ~30 个 key (见 §9)                     │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  后端 (api/)                                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ guidance_progress.py (新) — 2.1 实施助手清单状态        │  │
│  │  ├─ GET    /api/guidance/implementation              │  │
│  │  ├─ PATCH  /api/guidance/implementation/<task_id>    │  │
│  │  ├─ POST   /api/guidance/implementation/<task_id>/note │
│  │  ├─ GET    /api/guidance/implementation/report       │  │
│  │  └─ POST   /api/guidance/implementation/import-business-entities │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ skill_usage.py (扩展) — 新增 1 个 catalog endpoint     │  │
│  │  └─ GET    /api/skills/catalog                        │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ routes.py (扩展) — 注册上述路由                        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  存储                                                        │
│  localStorage (前端)                                          │
│  └─ guidance.dismissed.{page_id} = true|ts                  │
│  └─ guidance.first_use.completed = true                      │
│  └─ guidance.2_2.recent_entries = ['prompt', ...]            │
│                                                               │
│  ~/.hermes/guidance_progress.yaml (后端, per profile)         │
│  └─ implementation: { task_id: { done, by, ts, note } }      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 关键决策

| 项 | 决策 | 理由 |
|---|---|---|
| 模块边界 | `guidance.js` 仅作调度 + 共用框架；每个 page 是独立函数 | 单文件不超过 ~600 行；易测试 |
| 与 onboarding 关系 | onboarding.js 不改；guidance.js 监听 `onboarding_completed` 事件 | 单一职责 |
| 与主应用耦合 | 通过事件总线（`window.dispatchEvent`）+ 共享 localStorage key | 解耦；不修改 boot.js 主流程 |
| 与 RBAC 关系 | 2.1 实施助手要求 role ∈ {admin, ops}；2.2/2.3/2.4 全员可见 | 实施人员权限概念已存在（最近 RBAC 工作） |
| 与 i18n 关系 | 所有用户可见文本走 `t()`，key 前缀 `guidance_*` | 与现有 i18n.js 约定一致 |
| 移动端 | 2.2/2.4 响应式适配；2.3 popover 在小屏自动降级为底部 sheet；2.1 全屏页在 <768px 折叠子任务 | 移动端是已有约束 |

### 3.3 触发器注册表（核心交互契约）

```js
// 在 guidance.js 顶部声明，所有触发逻辑集中
const TRIGGERS = {
  '2.1': {  // 实施助手（最高优先级）
    on: ['deployment_first_seen', 'business_line_no_assets', 'manual_nav'],
    surface: 'fullscreen_page',
    auto_show: true,
  },
  '2.2': {  // 首次使用
    on: ['profile_new', 'onboarding_completed', 'manual_nav'],
    surface: 'modal',
    auto_show: true,
  },
  '2.3': {  // 新会话引导
    on: ['new_session_empty', 'manual_nav'],
    surface: 'inline',
    auto_show: false,  // 仅作为空状态辅助，不强制弹
  },
  '2.4': {  // 技能发现
    on: ['enter_skill_center', 'first_skill_use:<category>', 'manual_nav'],
    surface: 'popover',
    auto_show: true,
  },
};
```

---

## 4. 引导页详细设计

### 4.1 引导页 2.1：实施助手引导页（最高优先级）

**UI 形态**：全屏覆盖页 + 侧栏常驻入口（带未完成 badge）

**触发场景**：
- (a) 部署完成后首次进入主应用
- (b) 主动点击侧栏「📋 实施助手」入口
- (c) 检测到当前业务线无资产数据时高亮提示

**核心痛点**：
- 部署完成后不知道下一步要做什么
- 实施步骤散落在文档/Skill/CLI 多个入口
- 实施过程中没有进度跟踪，遗漏关键步骤
- 没有标准化验证流程

**3 大子任务 / 12 步**：

| # | 子任务 | 步骤 ID | 标题 | 关键交互 |
|---|---|---|---|---|
| 1.1 | 业务线实体关系表整理 | `1.1_view_doc` | 查看文档说明 | 跳转文档链接 |
| 1.2 | | `1.2_download_tpl` | 下载模板 | 下载 CSV 模板 |
| 1.3a | | `1.3_validate` | 校验文件 | 上传 + 预校验 |
| 1.3b | | `1.3_import` | 导入实体表 | 上传 + 进度可视化 |
| 1.3c | | `1.3_verify` | 验证导入结果 | 显示导入统计 |
| 2.1 | 知识库整理（故障FAQ） | `2.1_view_template` | 查看 FAQ 模板 | 渲染模板示例 |
| 2.2 | | `2.2_batch_import` | 批量导入知识库 | 上传 + 校验 |
| 2.3 | | `2.3_verify_search` | 验证可搜索 | 跳转知识库测试 |
| 3.1 | 巡检+诊断技能验证 | `3.1_select_business_line` | 选择业务线 | 下拉选择 |
| 3.2 | | `3.2_run_inspection` | 执行全链路巡检 | 触发巡检技能 |
| 3.3 | | `3.3_run_diagnosis` | 执行故障诊断 | 触发诊断技能 |
| 3.4 | | `3.4_record_result` | 记录验证结果 | 标记通过/不通过 |

> 注：原文档 9 步细化为 12 步，便于实施人员逐步打勾追踪进度。

**状态形状**（后端 YAML）：

```yaml
implementation:
  '1.1_view_doc':
    done: true
    by: 'alice'
    ts: 1722000000
    note: ''
  '1.2_download_tpl':
    done: true
    by: 'alice'
    ts: 1722000100
    note: ''
  '1.3_import':
    done: false
    by: null
    ts: null
    note: '关联 ZKREQ-130'
  # ... 共 12 项
```

**前端 State**：

```js
GuidanceManager.state['2.1'] = {
  loaded: false,
  tasks: [...],  // 从 /api/guidance/implementation 拉
  collapsed: { 1: true, 2: true, 3: false },  // 默认展开第 3 个（最关键）
  editingNote: null,
  currentUser: null,
};
```

**UI 草图**（全屏页）：

```
┌─────────────────────────────────────────────┐
│  📋 实施助手 · 部署后使用条件检查               │
├─────────────────────────────────────────────┤
│  总进度： 2/12 已完成                          │
│  ████░░░░░░░░░░░░░░░░ 17%                   │
│  当前用户：alice  ·  [ 重置进度 ]              │
├─────────────────────────────────────────────┤
│  ▾ 1. 业务线实体关系表整理  ✅ 2/5            │
│    ⬜ 1.1 查看文档说明                          │
│    ⬜ 1.2 下载模板                             │
│    ⬜ 1.3a 校验文件                            │
│    ⬜ 1.3b 导入实体表                          │
│    ⬜ 1.3c 验证导入结果                        │
│                                              │
│  ▾ 2. 知识库整理（故障FAQ）  ⬜ 0/3            │
│    ⬜ 2.1 查看 FAQ 模板                        │
│    ⬜ 2.2 批量导入知识库                       │
│    ⬜ 2.3 验证可搜索                          │
│                                              │
│  ▸ 3. 巡检+诊断技能验证  ⬜ 0/4                │
│                                              │
│  [ 导出进度报告 ]  [ 重置进度 ]                │
└─────────────────────────────────────────────┘
```

**关键交互**：

- **勾选**：每行 checkbox → PATCH → 更新进度条
- **添加备注**：每行"+ 备注"按钮 → 内联 textarea → POST note
- **批量导入**：上传文件 → 显示进度条 + 错误聚合
- **导出报告**：`GET /api/guidance/implementation/report?format=md` → 下载 .md

---

### 4.2 引导页 2.2：运维助手使用引导页（首次使用）

**UI 形态**：居中 modal，多步骤走完（4 步）

**触发场景**：
- (a) 首次登录完成 onboarding 后（`profile_new=true`）
- (b) 用户主动点击侧栏「查看使用引导」入口

**4 步流程**：

```
[1/4] 欢迎页 → [2/4] 核心能力（4 个卡片）→ [3/4] 使用示例（3 个场景）→ [4/4] 开始按钮
```

**4 个能力卡片**：

| 卡片 | 图标 | 一句话 |
|---|---|---|
| 巡检 | 🔍 | 一键巡检生产环境，输出完整报告 |
| 诊断 | 🩺 | 故障时自动定位根因 + 修复建议 |
| 知识查询 | 📚 | 查询内部资产、组件、文档 |
| 操作 | ⚡ | 安全执行运维操作（含审批） |

**3 个使用示例**（"我想要..."）：

1. 「我想要巡检一下 Redis 集群」→ 触发 zabbix_redis 技能
2. 「我想要查一下生产环境的所有 DB 连接数」→ 触发 db_inventory 技能
3. 「我想要知道上周发生过的 P1 故障」→ 触发 knowledge_search

**交互细节**：
- 每步可点「跳过」立即关闭整个引导
- 每步底部有「上一步 / 下一步」按钮
- 完成第 4 步后写入 `localStorage.guidance.first_use.completed = true`
- 后续可通过侧栏入口再次查看（不消耗完成状态）

**持久化**：
- 仅 localStorage：`guidance.first_use.completed` + `guidance.first_use.dismissed`
- 无后端状态

---

### 4.3 引导页 2.3：会话开始引导页（新会话入口）

**UI 形态**：内嵌在空会话组件，**不弹浮层**

**触发场景**：
- (a) 点击「+ 新建会话」按钮
- (b) 进入空会话页（`_renderEmptyState()`）

**3 个进入方向卡片**：

```
┌─────────────────────────────────────┐
│  💬 直接提问                          │
│  输入你想问的问题                      │
├─────────────────────────────────────┤
│  📋 任务下发                          │
│  描述要完成的运维任务                  │
├─────────────────────────────────────┤
│  🔧 技能调用                          │
│  从技能库选择需要的技能                │
├─────────────────────────────────────┤
│  [ 跳过，自己输入 ]                    │
└─────────────────────────────────────┘
```

**交互细节**：
- 点击卡片 → 自动聚焦到 composer + 预填示例 prompt
- 显示最近用过的入口（从 localStorage 读取 `recent_entries`）
- 「跳过，自己输入」按钮 → 隐藏整个组件，仅显示原始 composer
- 点击任一卡片时，记录到 `recent_entries`（最多 3 个，按使用频率排序）

**持久化**：
- 仅 localStorage：`guidance.2_3.recent_entries`
- 无后端状态

---

### 4.4 引导页 2.4：技能使用引导页（技能能力发现）

**UI 形态**：popover（首次进技能中心）+ 技能卡片"?"图标（随时查看）+ 技能中心内页

**3 层结构**：

| 层 | 形态 | 触发 |
|---|---|---|
| L1 场景匹配器 | 浮层 popover | 首次进技能中心 |
| L2 技能分类导航 | 技能中心顶部 tab | 总是 |
| L3 技能详情卡 | 卡片展开 | 点击"?"图标 |

**L1 场景匹配器**（首次进技能中心自动弹出）：

```
"你想做什么？"
  [巡检]  [诊断]  [查询]  [操作]
  ↓ 点击后展示该类别的技能列表（顶部）
```

**技能分类**：

| 类别 | icon | 现有技能示例（占位，1.1.0 验证后确认） |
|---|---|---|
| 巡检 | 🔍 | zabbix_redis, zabbix_db, host_info |
| 诊断 | 🩺 | log_analysis, root_cause_locator |
| 查询 | 📚 | knowledge_search, asset_inventory |
| 操作 | ⚡ | safe_exec（带审批） |

> 分类元数据来自技能 frontmatter 的 `category:` 字段；缺省的归到「其他」。

**L3 技能详情卡**：

```
┌─────────────────────────────────────┐
│ 🔍 zabbix_redis                       │
│ "一键巡检 Redis 集群指标"             │
│ ────────────────────────────────     │
│ 输入参数：集群名（可选）              │
│ 输出：QPS / 内存 / 连接数 / 慢查询     │
│ ────────────────────────────────     │
│ [试试这个] [查看完整文档]              │
└─────────────────────────────────────┘
```

**数据流**：

```
进入技能中心 → GET /api/skills/catalog → 渲染分类 + 卡片
首次进入 → 弹 L1 popover → 选择类别 → 高亮对应 tab
点击卡片"?" → 拉技能 frontmatter → 渲染 L3 详情
点击"试试这个" → 预填 composer → 跳到会话
```

**持久化**：
- localStorage：`guidance.2_4.popover_seen`（每个 session）
- 后端：catalog 来自 `api/skill_usage.py`，**2.4 引导页本身不存任何状态**

---

## 5. 数据流与状态管理

### 5.1 单例：`GuidanceManager`

```js
// guidance.js 顶部
const GuidanceManager = {
  state: {
    '2.1': { loaded: false, tasks: [], collapsed: {1:true,2:true,3:false}, editingNote: null },
    '2.2': { dismissed: false, completed: false, currentStep: 0 },
    '2.3': { recentEntries: ['prompt'], collapsed: false },
    '2.4': { catalogLoaded: false, activeCategory: null, seenPopover: false },
  },

  triggers: TRIGGERS,  // 见 §3.3

  init() {
    this._hydrateFromLocalStorage();
    this._registerEventListeners();
    this._registerSidebarEntry();  // 侧栏加 "📚 引导中心" 入口
  },

  evaluate(eventName, payload) {
    for (const [pageId, cfg] of Object.entries(this.triggers)) {
      if (cfg.on.includes(eventName) && this._shouldShow(pageId, eventName, payload)) {
        this._dispatch(pageId, cfg.surface, payload);
      }
    }
  },

  _dispatch(pageId, surface, payload) {
    switch (pageId) {
      case '2.1': return Page2_1_Implementation.openFullscreen({ autoTriggered: payload.autoTriggered });
      case '2.2': return Page2_2_FirstUse.show({ autoTriggered: payload.autoTriggered });
      case '2.3': return Page2_3_NewSession.render({ inEmptyState: true });
      case '2.4': return Page2_4_SkillDiscovery.showPopover();
    }
  },
};
```

### 5.2 触发流（按生命周期）

```
boot.js 启动
  ↓
检查 localStorage:
  - guidance.2_2.completed === undefined? → 触发 'profile_new'
  - guidance.2_4.popover_seen === undefined? → 触发 'enter_skill_center' 准备
  - 后端 GET /api/guidance/implementation → 检查 deployment_first_seen
  ↓
GuidanceManager.init() 挂载事件监听 + 侧栏入口
  ↓
事件触发（任意一个）
  ├─ 'profile_new'              → 2.2 自动展示 modal
  ├─ 'onboarding_completed'     → 2.2 自动展示（兜底）
  ├─ 'deployment_first_seen'    → 2.1 自动展开全屏页
  ├─ 'business_line_no_assets'  → 2.1 高亮 "1.3b 导入" 子任务
  ├─ 'new_session_empty'        → 2.3 渲染空状态组件（不强制弹）
  ├─ 'enter_skill_center'       → 2.4 弹 popover（首次）
  └─ 'manual_nav' (侧栏点击)    → 对应 page 全屏打开
```

### 5.3 持久化数据流

**前端 localStorage**（仅个人引导状态）：

```
写：Page 完成/跳过 → GuidanceManager._persistLocal(pageId)
读：boot 启动时 → GuidanceManager._hydrateFromLocalStorage()
```

**后端 YAML**（仅 2.1 实施清单）：

```
写：用户勾选任务 → PATCH /api/guidance/implementation/<task_id>
                    → api/guidance_progress.py → 写 ~/.hermes/guidance_progress.yaml
读：进入 2.1 页  → GET /api/guidance/implementation
                  → api/guidance_progress.py → 读 yaml
导出报告         → GET /api/guidance/implementation/report
                  → 服务端渲染 Markdown 字节流
```

### 5.4 跨页协同（去重 / 兜底）

```js
_shouldShow(pageId, eventName, payload) {
  const key = `guidance.${pageId.replace('.', '_')}.auto_shown_at`;
  const lastShown = sessionStorage.getItem(key);
  if (lastShown && Date.now() - parseInt(lastShown, 10) < 600_000) {
    return false;  // 10 分钟内已自动展示过
  }
  if (eventName === 'manual_nav') return true;  // 手动点不算
  if (this.state[pageId].dismissed) return false;
  return true;
}
```

### 5.5 与现有系统的集成点（不改 boot.js 主流程）

```js
// 在 boot.js 末尾追加 1 行（最小侵入）
window.__guidanceMgr = GuidanceManager.init();

// 现有 onboarding 完成回调（onboarding.js）
window.addEventListener('hermes:onboarding_complete', () => {
  GuidanceManager.evaluate('onboarding_completed', { autoTriggered: true });
});

// 现有 license 激活回调（最近的 license 流程）
window.addEventListener('hermes:license_activated', () => {
  GuidanceManager.evaluate('deployment_first_seen', { autoTriggered: true });
});

// 技能中心入口（panels.js 现有 loadSkillsPanel）
const _origLoadSkills = window.loadSkillsPanel;
window.loadSkillsPanel = function (...args) {
  const ret = _origLoadSkills.apply(this, args);
  GuidanceManager.evaluate('enter_skill_center', { autoTriggered: true });
  return ret;
};
```

---

## 6. API 设计

### 6.1 端点总览

| 方法 | 路径 | 模块 | 用途 | 权限 |
|---|---|---|---|---|
| GET | `/api/guidance/implementation` | `api/guidance_progress.py` | 拉取 2.1 实施清单状态 | admin, ops |
| PATCH | `/api/guidance/implementation/<task_id>` | 同上 | 勾选 / 取消勾选单个任务 | admin, ops |
| POST | `/api/guidance/implementation/<task_id>/note` | 同上 | 添加 / 更新备注 | admin, ops |
| GET | `/api/guidance/implementation/report` | 同上 | 导出进度报告（Markdown） | admin, ops |
| POST | `/api/guidance/implementation/import-business-entities` | 同上 | 1.3 步骤的实体关系表导入 | admin, ops |
| GET | `/api/skills/catalog` | `api/skill_usage.py` | 2.4 引导用技能 catalog | all |

### 6.2 `GET /api/guidance/implementation`

**Response 200**：

```json
{
  "schema_version": 1,
  "deployment_id": "dep-2026-07-15-001",
  "first_seen_at": 1722000000,
  "tasks": [
    {
      "id": "1.1_view_doc",
      "group": 1,
      "group_title": "业务线实体关系表整理",
      "title": "查看文档说明",
      "done": true,
      "by": "alice",
      "ts": 1722000000,
      "note": ""
    }
    // ... 共 12 项
  ],
  "summary": {
    "total": 12,
    "done": 2,
    "by_group": { "1": 2, "2": 0, "3": 0 }
  }
}
```

**Permission gate**（路由 handler 头部）：

```python
if not (request.user.role in {"admin", "ops"}):
    return jsonify({"error": "forbidden"}), 403
```

### 6.3 `PATCH /api/guidance/implementation/<task_id>`

**Request body**：

```json
{ "done": true, "note": "已导入 12 个业务线" }
```

**Response 200**：

```json
{ "ok": true, "task": { /* 单条任务对象 */ } }
```

**Response 404**：`{ "error": "unknown_task", "task_id": "..." }`
**Response 403**：`{ "error": "forbidden" }`
**Response 400**：`{ "error": "validation", "detail": "task_id 必须在 12 项白名单中" }`

**白名单校验**：

```python
ALLOWED_TASKS = frozenset({
  "1.1_view_doc", "1.2_download_tpl", "1.3_validate", "1.3_import", "1.3_verify",
  "2.1_view_template", "2.2_batch_import", "2.3_verify_search",
  "3.1_select_business_line", "3.2_run_inspection", "3.3_run_diagnosis", "3.4_record_result",
})  # 共 12 项
```

### 6.4 `POST /api/guidance/implementation/<task_id>/note`

独立的 note 更新接口（不依赖 done 状态）。

**Request body**：`{ "note": "..." }`

### 6.5 `GET /api/guidance/implementation/report`

**Query**：`?format=md`（默认 md；预留 `?format=pdf`，1.1.0 不实现）

**Response 200**：

```
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="implementation-report-{date}.md"

# 实施助手进度报告

**部署 ID**：dep-2026-07-15-001
**生成时间**：2026-07-27 14:30
**总进度**：2/12（17%）

## 1. 业务线实体关系表整理 ✅ 2/5
- [x] 1.1 查看文档说明 (by alice, 2026-07-27 10:00)
- [x] 1.2 下载模板 (by alice, 2026-07-27 10:05)
- [ ] 1.3a 校验文件
- [ ] 1.3b 导入实体表 — 关联 ZKREQ-130
- [ ] 1.3c 验证导入结果

## 2. 知识库整理（故障FAQ）⬜ 0/3
...
```

### 6.6 `POST /api/guidance/implementation/import-business-entities`

**Request**：multipart/form-data，文件字段名 `file`

**Validation**：
- 文件类型：`.csv`（v1.1.0 仅 csv；xlsx 后续）
- 必填列：`业务线名称`, `主机IP`, `主机角色`
- 行数上限：10000（防止 OOM）

**Response 200**：

```json
{
  "ok": true,
  "imported_rows": 1234,
  "failed_rows": [
    { "line": 17, "field": "主机IP", "reason": "格式不合法（应为 IP）" }
  ],
  "task_updated": "1.3_import"
}
```

**Response 400**：`{ "error": "missing_columns", "missing": ["业务线名称"] }`
**Response 400**：`{ "error": "unsupported_format", "format": "xlsx" }`（v1.1.0 不支持）

### 6.7 `GET /api/skills/catalog`（扩展现有 skill_usage.py）

**Response 200**：

```json
{
  "schema_version": 1,
  "categories": [
    {
      "id": "inspect",
      "title": "巡检",
      "icon": "🔍",
      "skills": [
        {
          "slug": "zabbix_redis",
          "name": "Redis 集群巡检",
          "description": "一键巡检 Redis 集群指标",
          "example_prompt": "用 zabbix_redis 技能检查 Redis 集群状态",
          "tags": ["redis", "zabbix"]
        }
      ]
    }
  ],
  "total_skills": 12
}
```

**分类逻辑**：复用现有 `api/skill_usage.py` 的扫描结果，按技能 frontmatter 的 `category:` 字段分组；缺省的归到「其他」。

---

## 7. 错误处理

### 7.1 错误分类与处理策略

| 错误类型 | 触发场景 | 处理策略 | UI 反馈 |
|---|---|---|---|
| 网络失败 | PATCH/POST 请求超时（>10s） | 自动重试 1 次 + 标记本地 dirty state | Toast: 「网络异常，正在重试...」 |
| 401 未登录 | 任意请求 | 触发重新登录流程 | Modal: 「会话过期，请重新登录」 |
| 403 权限不足 | 非 admin/ops 访问 2.1 API | 隐藏入口 + 友好提示 | Inline: 「此功能仅对运维/管理员开放」 |
| 404 任务 ID 非法 | PATCH 未知 task_id | 返回 400（前端应避免） | Console error；无 UI 反馈 |
| 400 校验失败 | 导入文件缺列 | 显示缺失列名 | Modal: 「缺少必填列：业务线名称、主机IP」 |
| 文件解析失败 | CSV 格式错误 | 返回行号 + 字段 + 原因 | Modal: 错误表格 + 「下载错误报告」按钮 |
| YAML 写失败 | 磁盘满 / 权限 | 后端 5xx + 标记本地 dirty | Toast: 「保存失败，请稍后重试」 + 重试按钮 |
| localStorage 满 | 用户数据过大 | 静默降级：仅内存态 | Console warn；功能照常用但不持久化 |
| 技能 catalog 加载失败 | 扫描错误 | 用空数组兜底 | 空状态文案：「暂无可用技能」 |
| 触发器死循环 | 监听器相互触发 | 10 分钟去重窗口（§5.4） | 不弹 UI |
| 用户手动重置 | 主动点「重置进度」 | 二次确认 + 清空 yaml + 清 localStorage | Modal 确认 + Toast 完成 |

### 7.2 错误处理实现要点

**前端统一错误处理**（在 `api()` 包装层）：

```js
// static/guidance.js
async function _api(path, opts = {}) {
  const res = await api(path, opts);  // 复用现有 api() 包装
  if (!res.ok) {
    if (res.status === 401) {
      GuidanceManager._handle401();
    } else if (res.status === 403) {
      GuidanceManager._handle403(path);
    } else if (res.status >= 500) {
      GuidanceManager._handle5xx(path, res);
    }
    throw new Error(`api ${path} failed: ${res.status}`);
  }
  return res;
}
```

**YAML 写失败的兜底**：

```python
# api/guidance_progress.py
def _atomic_write_yaml(path: Path, data: dict) -> None:
    tmp = path.with_suffix('.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)  # 原子替换，避免半写
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"guidance_progress.yaml write failed: {e}") from e
```

**导入文件的错误聚合**：

```python
# api/guidance_progress.py — _validate_business_entity_csv()
errors = []
for line_no, row in enumerate(csv_reader, start=2):  # 1 是 header
    if not row.get('业务线名称'):
        errors.append({"line": line_no, "field": "业务线名称", "reason": "必填"})
    ip = row.get('主机IP', '').strip()
    if not _is_valid_ipv4(ip):
        errors.append({"line": line_no, "field": "主机IP", "reason": f"格式不合法（{ip}）"})

if errors:
    return jsonify({
        "ok": False,
        "error": "validation",
        "failed_rows": errors[:100],  # 最多返回 100 行错误，避免响应过大
        "total_failed": len(errors),
    }), 400
```

### 7.3 UI 反馈原则

- **Toast**（顶部短提示，3 秒自动消失）：网络异常、保存成功/失败、跳过
- **Modal**（仅用于）：文件导入失败（要展示错误表格）、401 会话过期（要重定向）、重置进度（二次确认）
- **Inline**（页面内）：权限不足提示、操作说明

### 7.4 日志策略

- **前端**：所有 API 失败打 `console.warn('[guidance] xxx failed:', err)`，**不打 error**（避免误判为异常）
- **后端**：yaml 写失败、文件解析失败用 `logger.error()`；403/404 用 `logger.info()`（正常拒绝）

---

## 8. 测试策略

### 8.1 测试分层

| 层 | 范围 | 工具 | 目标覆盖率 |
|---|---|---|---|
| 单元测试 | `api/guidance_progress.py` 的纯函数（白名单校验、YAML IO、CSV 校验） | pytest | 90%+ |
| 集成测试 | `/api/guidance/implementation*` 端到端（HTTP 路由 + 鉴权 + yaml 持久化） | pytest + TestClient | 全部 happy path + 关键错误 |
| 前端单元 | `static/guidance.js` 触发器逻辑、状态机、模板渲染 | jsdom 或纯 JS | 核心函数 80%+ |
| E2E | 4 个 page 的完整用户旅程（启动 → 触发 → 交互 → 完成） | Playwright | 至少 1 条/页 |
| 手动测试 | UI 视觉、动画、移动端适配、跨浏览器 | 浏览器 | 上线前 checklist |

### 8.2 pytest 后端测试清单

**`tests/test_guidance_progress.py`**（新增）：

```python
# 覆盖矩阵
test_init_creates_yaml_file          # 首次访问自动建空 yaml
test_get_returns_12_tasks             # schema 完整性
test_get_summary_calculation         # total/done/by_group 正确
test_patch_marks_task_done           # 正常勾选
test_patch_marks_task_undone         # 取消勾选
test_patch_records_user_and_ts       # who + when
test_patch_rejects_unknown_task_id   # 400
test_patch_requires_admin_or_ops     # 403 for viewer
test_note_endpoint_separate          # note 不影响 done 状态
test_report_endpoint_returns_md      # 报告格式 + Content-Type
test_import_csv_happy_path           # 完整 csv 导入
test_import_csv_missing_column       # 缺业务线名称 → 400
test_import_csv_invalid_ip           # 主机IP 格式错 → row-level error
test_import_csv_size_limit           # 10000 行截断
test_import_xlsx_rejected_in_v110    # v1.1.0 仅 csv
test_yaml_atomic_write               # 半写不会损坏
test_yaml_concurrent_writes          # 多 PATCH 不丢更新
test_no_state_leak_between_profiles  # 切换 profile 不串数据
```

**Mock 模式**：参考现有 `tests/test_custom_providers_slug.py` 的 `python -c` 模式（参见 MEMORY.md），不依赖 conftest 的 test_server。

### 8.3 前端单元测试清单

**`tests/js/test_guidance_triggers.test.mjs`**（新增，vanilla JS via jsdom）：

```js
test_trigger_2_1_on_deployment_first_seen
test_trigger_2_1_skipped_when_dismissed
test_trigger_2_2_on_profile_new
test_trigger_2_2_skipped_when_completed
test_trigger_2_3_renders_in_empty_state_only
test_trigger_2_4_popover_only_first_time_per_session
test_dedupe_window_10_minutes
test_localStorage_fallback_when_quota_exceeded
test_state_rehydration_after_reload
test_recent_entries_sorted_by_usage_frequency
```

### 8.4 E2E Playwright 用例

**`tests/e2e/test_guidance_pages.spec.js`**（新增）：

```js
test('2.2 首次使用 4 步骤 modal 流程')
test('2.1 实施清单勾选 + 持久化')
test('2.1 CSV 导入错误聚合')
test('2.3 空会话显示 3 个入口')
test('2.4 技能中心首次 popover')
```

### 8.5 手动测试 checklist（上线前必做）

```
□ 移动端 (iPhone 14) 4 个 page 都能正常显示
  □ 2.1 全屏页在 < 768px 折叠子任务
  □ 2.2 modal 在移动端宽度自适应
  □ 2.4 popover 在小屏降级为底部 sheet
□ 浏览器兼容
  □ Chrome 120+、Safari 17+、Firefox 120+
  □ 服务端 worker / cache 不影响引导触发
□ RBAC 边界
  □ viewer 角色访问 2.1 → 完全隐藏（不显示入口）
  □ admin 全功能可见
  □ ops 可见但某些操作受限（如导出 PDF 待后续）
□ i18n 完整性
  □ 所有 UI 文案走 t()，无硬编码中文/英文
  □ 切换语言 → 引导页文案同步
□ 边界情况
  □ 没有 license 时不展示任何引导
  □ license 刚激活（首次部署）→ 2.1 立刻自动展开
  □ 同时多账号登录 → 不串数据
```

### 8.6 测试数据准备

**fixtures**：
- `tests/fixtures/business_entities_valid.csv`（5 行示例数据）
- `tests/fixtures/business_entities_missing_col.csv`
- `tests/fixtures/business_entities_bad_ip.csv`
- `tests/fixtures/guidance_progress_initial.yaml`

### 8.7 CI 集成

- 所有新测试加进 `pytest tests/` 默认收集
- ruff 仍走 `ruff check static/guidance.js`（无需改 lint 配置）
- E2E 走现有 Playwright 工作流（仅 PR 触发，不阻塞日常）

---

## 9. i18n 清单

新增 ~30 个 i18n key（`guidance_*` 前缀）。中英双语。

| key | 中文 | 英文 |
|---|---|---|
| `guidance_sidebar_entry` | 引导中心 | Guidance Center |
| `guidance_2_1_title` | 实施助手 · 部署后使用条件检查 | Implementation Assistant |
| `guidance_2_1_progress` | 总进度：{done}/{total} 已完成 | Progress: {done}/{total} |
| `guidance_2_1_export` | 导出进度报告 | Export Progress Report |
| `guidance_2_1_reset` | 重置进度 | Reset Progress |
| `guidance_2_1_reset_confirm` | 确定要重置所有进度吗？此操作不可恢复。 | Reset all progress? This cannot be undone. |
| `guidance_2_1_group_1` | 业务线实体关系表整理 | Business Line Entity Table |
| `guidance_2_1_group_2` | 知识库整理（故障FAQ） | Knowledge Base (FAQ) |
| `guidance_2_1_group_3` | 巡检+诊断技能验证 | Inspection + Diagnosis Validation |
| `guidance_2_1_task_1_1` | 查看文档说明 | View Documentation |
| `guidance_2_1_task_1_2` | 下载模板 | Download Template |
| `guidance_2_1_task_1_3a` | 校验文件 | Validate File |
| `guidance_2_1_task_1_3b` | 导入实体表 | Import Entity Table |
| `guidance_2_1_task_1_3c` | 验证导入结果 | Verify Import |
| `guidance_2_1_task_2_1` | 查看 FAQ 模板 | View FAQ Template |
| `guidance_2_1_task_2_2` | 批量导入知识库 | Batch Import Knowledge |
| `guidance_2_1_task_2_3` | 验证可搜索 | Verify Searchable |
| `guidance_2_1_task_3_1` | 选择业务线 | Select Business Line |
| `guidance_2_1_task_3_2` | 执行全链路巡检 | Run Full Inspection |
| `guidance_2_1_task_3_3` | 执行故障诊断 | Run Diagnosis |
| `guidance_2_1_task_3_4` | 记录验证结果 | Record Result |
| `guidance_2_1_import_btn` | 上传 CSV 文件 | Upload CSV File |
| `guidance_2_1_import_missing_col` | 缺少必填列：{cols} | Missing required columns: {cols} |
| `guidance_2_1_import_errors` | 共 {n} 行错误，已显示前 {shown} 行 | {n} errors total, showing first {shown} |
| `guidance_2_2_title` | 欢迎使用 ZK 运维智能体 | Welcome to ZK Ops Assistant |
| `guidance_2_2_skip` | 跳过引导 | Skip |
| `guidance_2_2_next` | 下一步 | Next |
| `guidance_2_2_done` | 开始体验 | Start |
| `guidance_2_3_title` | 开始一个新对话 | Start a New Conversation |
| `guidance_2_3_prompt` | 直接提问 | Ask a Question |
| `guidance_2_3_task` | 任务下发 | Send a Task |
| `guidance_2_3_skill` | 技能调用 | Use a Skill |
| `guidance_2_3_skip` | 跳过，自己输入 | Skip, I'll type |
| `guidance_2_4_title` | 你想做什么？ | What do you want to do? |
| `guidance_2_4_category_inspect` | 巡检 | Inspect |
| `guidance_2_4_category_diagnose` | 诊断 | Diagnose |
| `guidance_2_4_category_query` | 查询 | Query |
| `guidance_2_4_category_operate` | 操作 | Operate |
| `guidance_2_4_try_this` | 试试这个 | Try This |
| `guidance_2_4_view_docs` | 查看完整文档 | View Full Docs |

---

## 10. 实施计划（拆分 4 份）

| 计划 | 范围 | 依赖 | 优先级 |
|---|---|---|---|
| Plan A: 引导页 2.1（实施助手） | `guidance.js` 框架 + Page2_1 + 后端 `guidance_progress.py` + 5 个端点 + i18n + E2E | 无（独立） | P0 |
| Plan B: 引导页 2.2（首次使用） | Page2_2 modal + 4 步骤流程 + i18n + 触发集成 | Plan A（共享 GuidanceManager） | P1 |
| Plan C: 引导页 2.3（新会话） | Page2_3 空状态组件 + i18n + localStorage 持久化 | Plan A | P2 |
| Plan D: 引导页 2.4（技能发现） | Page2_4 popover + L3 详情卡 + 后端 `/api/skills/catalog` 扩展 | Plan A + 现有 skill_usage.py | P3 |

> 实施顺序：Plan A → Plan B → Plan C → Plan D。每个 Plan 走"spec → plan → implementation → review"完整循环。

---

## 11. 风险与开放问题

### 11.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 触发器互相干扰导致重复弹窗 | 用户困扰 | 10 分钟去重窗口（§5.4） |
| YAML 写并发冲突 | 多 PATCH 丢更新 | 原子替换 + 重试（§7.2） |
| 移动端 2.1 全屏页体验差 | 实施人员移动办公不便 | < 768px 折叠子任务，accordion 模式 |
| localStorage 跨 profile 共享 | 用户切换 profile 看到错状态 | localStorage 不存 profile 敏感状态，仅个人引导标记 |
| i18n key 命名冲突 | 翻译漏改 | 统一前缀 `guidance_*`，CI 检查重复 key |

### 11.2 开放问题（实施时确认）

1. **技能分类标准**：现有技能是否都有 `category:` frontmatter？缺省规则（归到"其他"）是否符合预期？
2. **2.1 入口位置**：侧栏常驻 vs 设置面板内？侧栏更显眼但占空间。
3. **多人协作权限**：ops A 勾选任务后，ops B 能修改吗？还是仅 admin 可修改？v1.1.0 默认双方都可改，后续可加"仅创建者可改"。
4. **导入性能**：10000 行 csv 在浏览器端预览还是服务端预览？v1.1.0 仅服务端校验，前端不做预览。
5. **重置进度的权限**：仅 admin 可重置，还是创建者（first_done_by）可重置自己的？v1.1.0 默认 admin 全权重置。

---

## 12. 验收标准

- [ ] 4 个引导页在主流浏览器（Chrome/Safari/Firefox）正确渲染
- [ ] 所有触发场景（§3.3）按预期工作
- [ ] RBAC 权限边界测试通过（§8.5）
- [ ] 移动端 < 768px 体验可用（§8.5）
- [ ] pytest 后端测试覆盖率 ≥ 90%（§8.2）
- [ ] 前端单元测试覆盖核心函数 ≥ 80%（§8.3）
- [ ] E2E Playwright 至少 1 条/页通过（§8.4）
- [ ] i18n 中英双语完整，无硬编码（§9）
- [ ] YAML 持久化测试覆盖并发 / 原子写 / 跨 profile（§8.2）
- [ ] CSV 导入错误聚合正确，错误报告可下载（§6.6、§7.1）
- [ ] 报告导出 Markdown 格式正确（§6.5）

---

## 13. 参考

- 现有 spec：`docs/superpowers/specs/2026-07-15-custom-provider-自定义Provider配置-设计.md`（格式参考）
- 现有 onboarding：`static/onboarding.js`（不要改动，仅参考）
- 现有技能后端：`api/skill_usage.py`、`api/plugins.py`
- RBAC：`api/auth.py`、`api/admin.py`
- i18n：`static/i18n.js`、`static/messages.js`
- 触发事件总线：现有 `window.dispatchEvent` 模式
- 周报：`docs/工作日报/周报/2026-W29 07.20—07.24 周报（ZK运维智能体）.md`