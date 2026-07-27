# 图库管理面板重做设计规格

**日期**：2026-07-27
**作者**：Claude
**分支**：`feat/graph-management`
**状态**：设计中

## 0. 背景

2026-06-29 已完成图库管理模块的第一版（`docs/superpowers/specs/2026-06-29-graph-management-design.md`），在 `feat/graph-management` 分支上落地。但实际运行后用户反馈实现"太差劲"，经排查确认以下问题：

### 0.1 已确认的 bug

1. **搜索 API 响应格式不匹配（致命）**：前端 `doPreviewSearch` / `doFullSearch`（`static/graph.js:429-460`）调用 `await res.json()` 后当作数组遍历，但后端 `search_graph`（`api/graph.py:446-470`）返回的是 `{results, query, count}` 字典。结果搜索静默失败，没有任何节点被高亮或加载。
2. **Table 视图空白**：`showTableView`（`static/graph.js:607-612`）调用 `loadNodeList()` → `/api/graph/nodes` 但后端要求 `label` 参数（`api/graph.py:543`），未传 label 时返回 400，导致 Table 模式永远空白 —— 这就是用户截图里看到的"Table"标签。
3. **状态栏被覆盖**：`updateStatus`（`static/graph.js:1021`）在 schema 加载后用 `innerHTML` 覆盖整个 `#graphStatus` 内部 HTML，把 `Nodes / Relationships` 两个 `<span>` 直接删掉，因此底部计数器始终是 `0 0`。
4. **空状态 UX 死路**：面板首次打开只显示"Search for a node to visualize the graph"提示，用户没有任何入口知道该做什么，体感是面板"死了"。
5. **Cypher `*1..$depth` 参数化上限**：`api/graph.py:276, 477` 使用参数化变长路径上限，部分 Neo4j 版本不支持，会导致拓扑查询失败。
6. **CSS 选择器错乱**：`style.css:2659-2698` 使用 `#graph-panel` / `#graph-canvas` 等 kebab-case ID，但实际 DOM 是 `#panelGraph` / `#graphCanvas`（驼峰式）。靠 `style.css:8245-8253` 的别名兜底，旧规则是死代码。
7. **布局下拉像 Tab**：`<select id="graphLayoutSelect">` 的三个选项 `COSE / Breadthfirst / Table` 视觉上像 tab，但实际是布局选择器，造成用户认知错乱。

### 0.2 设计目标

- 修复以上 7 项 bug
- 把面板从"半成品"做成"真正可用"——具备完整 CRUD、清晰导航、有意义的初始状态
- 让 Neo4j 未配置 / 不可达时仍可演示（Mock 降级）
- 保持现有 API 路由的向后兼容（`tests/test_graph_api.py` 现有断言不破）

## 1. 架构总览

将"图库"做成一组**职责单一、可独立测试**的模块：

```
┌────────────────────────────────────────────────────────────┐
│  static/graph_main.js  ─── 主控：面板初始化、tab 切换、状态 │
│       ├── graph_view_graph.js  ─ Cytoscape 视图（重写）     │
│       ├── graph_view_table.js  ─ 表格视图（新建）           │
│       ├── graph_view_json.js   ─ JSON 视图（新建）          │
│       └── graph_crud.js        ─ CRUD 对话框（新建）        │
├────────────────────────────────────────────────────────────┤
│  api/graph.py           ─ 路由层（瘦壳）：解析请求 → 存储层  │
│  api/graph_store.py     ─ 存储接口（Protocol）              │
│       ├── api/graph_neo4j.py  ─ Neo4j 实现                  │
│       └── api/graph_mock.py   ─ SQLite 实现（新建）         │
├────────────────────────────────────────────────────────────┤
│  api/graph.py /health   ─ 新增：前端探测后端类型             │
└────────────────────────────────────────────────────────────┘
```

存储层**自动选择**：服务启动时优先尝试 Neo4j；连接失败 / 未配置则降级到 Mock；通过 `/api/graph/health` 让前端知道当前后端是哪种。

## 2. 存储层

### 2.1 `api/graph_store.py` — 接口

定义 `GraphStore` Protocol，所有方法以 `dict` / `list[dict]` 进出，不暴露 Neo4j 类型：

```python
class GraphStore(Protocol):
    def health(self) -> dict: ...
    def schema(self) -> dict: ...
    def search(self, query: str, label: str | None = None, limit: int = 50) -> dict: ...
    def list_nodes(self, label: str, limit: int = 200) -> dict: ...
    def get_node(self, element_id: str) -> dict | None: ...
    def get_relationship(self, element_id: str) -> dict | None: ...
    def list_relationships(self, element_id: str, direction: str = "both") -> list[dict]: ...
    def topology(self, element_id: str, depth: int = 1) -> dict: ...
    def create_node(self, labels: list[str], properties: dict) -> dict: ...
    def create_relationship(self, type_: str, start_id: str, end_id: str, properties: dict | None = None) -> dict: ...
    def update_node(self, element_id: str, properties: dict) -> dict: ...
    def delete_node(self, element_id: str) -> dict: ...
    def delete_relationship(self, element_id: str) -> dict: ...
    def seed_sample(self) -> dict: ...
```

### 2.2 `api/graph_neo4j.py` — Neo4j 实现

把现有 `api/graph.py` 里所有 Cypher / driver 调用搬过来，并修复：

- `topology` / `expand_node` 中 `*1..$depth` → 拆分为 `*1..N`，`N` 由 Python 端校验为 1-5 整数后**字符串拼接**到 cypher（避开参数化上限不支持的版本）
- `nodes(path)` / `rels(path)` 的 Cypher 改写，避免部分 Neo4j 版本不识别
- 所有 Cypher 经 `_validate_identifier` 兜底
- 缺 `NEO4J_PASSWORD` → `_err(503, "neo4j not configured")`
- 连接失败 → `_err(503, "neo4j unreachable")`
- 健康探测：未配置 `health()` 返回 `{"backend": "neo4j", "ok": False, "detail": "not_configured"}`
- `seed_sample` 在 Neo4j 模式下同样可用：通过 CREATE 语句插入示例节点 / 关系；首次调用幂等（按 `name` 唯一约束）

### 2.3 `api/graph_mock.py` — SQLite 实现

- 使用标准库 `sqlite3`，无需新增依赖
- 持久化文件：`data/graph.sqlite`（首次运行自动建表）
- 表结构：
  ```sql
  CREATE TABLE nodes (
    id TEXT PRIMARY KEY,         -- 形如 "mock-uuid"
    labels TEXT NOT NULL,        -- JSON 数组
    properties TEXT NOT NULL      -- JSON 对象
  );
  CREATE TABLE relationships (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    start_id TEXT NOT NULL,
    end_id TEXT NOT NULL,
    properties TEXT NOT NULL,    -- JSON
    FOREIGN KEY (start_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (end_id) REFERENCES nodes(id) ON DELETE CASCADE
  );
  ```
- `topology` 用 Python 端 BFS 实现，避免 Cypher 兼容问题
- `seed_sample` 内置 ZK 运维示例：Host / Service / Incident / Runbook 四类节点 + 关系（详见 §5.3）

### 2.4 `api/graph.py` — 瘦壳

- 只保留 `handle_graph_get / post / delete` 三个入口，把请求解析后分发给 `get_store()` 返回的实例
- `get_store()` 单例懒加载 + 进程内缓存；启动时**只尝试一次 Neo4j**，失败则永久降级到 Mock（避免每次请求重试）
- 启动检测放到 `bootstrap.py` / `server.py` 的启动流程中，调用一次 `store.health()` 把结果记入日志

## 3. API 契约

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/graph/health` | **新增**：返回 `{backend, ok, detail, stats}` |
| GET | `/api/graph/schema` | 修复：补 `stats: {node_count, relationship_count}` |
| GET | `/api/graph/search?q=&label=&limit=` | 保持 `{results, query, count}` 格式（前端已修解析） |
| GET | `/api/graph/nodes?label=&limit=` | 无 label 时返回 400 + 友好错误信息 |
| GET | `/api/graph/node/{id}` | — |
| GET | `/api/graph/relationship/{id}` | — |
| GET | `/api/graph/relationships/{id}?direction=` | — |
| GET | `/api/graph/topology/{id}?depth=` | 修复 Cypher；depth 由 Python 端校验 |
| POST | `/api/graph/nodes` | 接受 `{labels: [...], properties: {...}}` |
| POST | `/api/graph/relationships` | 接受 `{type, start_node_id, end_node_id, properties?}` |
| POST | `/api/graph/node/{id}/expand` | **移除**：现有前端实际只调用 GET `/topology/{id}`，无调用方 |
| DELETE | `/api/graph/node/{id}` | — |
| DELETE | `/api/graph/relationship/{id}` | — |
| POST | `/api/graph/seed` | **新增**：一键加载示例图谱，返回 `{nodes_added, relationships_added}` |

所有端点统一返回 `{ok: bool, data?: ..., error?: str}` 包装层；**新增包装层的同时在 `api/graph.py` 中保留旧格式透传**——即若 handler 返回的是 dict 而非包装层，则自动包一层。这样 `tests/test_graph_api.py` 中既有断言不破，新调用方按新格式解析即可。

## 4. 前端模块

### 4.1 `static/graph_main.js`（重写）

主控职责：
- `init()`：找 DOM、调 `/api/graph/health`、根据 backend 渲染顶部状态徽章、绑 tab 切换、绑搜索框（debounced）、绑 CRUD 入口
- 启动时：
  - 健康探测 → 显示后端类型徽章（`✓ Neo4j` / `⚠ Mock`）
  - 拉 schema → 缓存到 `state.schema`
  - 若 `backend == "mock"` 且 `schema.stats.node_count == 0` → 显示"一键加载示例"按钮
- 单例 `state`：`{backend, schema, currentView, selectedNodeId, ...}`
- 事件总线：tab 切换、节点选中、CRUD 完成时通知视图重渲染

### 4.2 `static/graph_view_graph.js`

Cytoscape 视图（基于现有 `initCytoscape` 重写）：
- mapper `data: { label, color, borderColor }`，从 schema 给 label 着色
- 搜索 → 用 `search.results`（**修 API 解析 bug**）
- 双击节点 → `/topology/{id}?depth=` 展开
- 右键菜单 → 调用 `graph_crud` 的 modal
- tab 切换到本视图时调 `cy.resize()` 触发重排（修 Cytoscape 在隐藏容器里不渲染的问题）

### 4.3 `static/graph_view_table.js`（新建）

- sub-tab：`[Nodes | Relationships]`
- 列：id / labels(type) / 第一个属性值 / 操作（编辑、删除、定位到 Graph）
- 排序、搜索（前端筛选）
- 点击行 → 切到 Graph 视图并定位

### 4.4 `static/graph_view_json.js`（新建）

- 左侧：树（节点 / 关系）
- 右侧：选中项的完整 JSON（pretty-print）
- 工具条：复制、下载当前选中

### 4.5 `static/graph_crud.js`（新建）

- 模态：创建节点（labels 多选 + properties 动态 KV 增删）
- 创建关系（type + 源/目标下拉）
- 编辑节点属性（双击 inline 编辑）
- 删除（带 confirm）
- 复用现有 `static/style.css` 的 modal 样式

### 4.6 `static/index.html` 修改

- 把 `panelGraph` 的 DOM 改成新结构：顶部 tab strip（Graph / Table / JSON）+ 工具栏 + 三视图容器
- 保留 `id="graphSearchInput"` 等关键 ID（向后兼容 + 最小 diff）
- **删除**旧的 `<select id="graphLayoutSelect">`（之前的 Table 选项 → 现在的视图 tab，避免认知错乱）。同时从 `graph_main.js` 删除所有 `getEl('graphLayoutSelect')` / `layoutSelect` 引用，避免运行时报 `null.addEventListener`

### 4.7 `static/style.css` 修改

- 删除 `style.css:2659-2698` 死代码（旧 kebab-case 选择器）
- 新增：
  - `.graph-tabs`（顶部 tab strip）
  - `.graph-toolbar-v2`（新工具栏）
  - `.graph-view-table`（表格视图）
  - `.graph-view-json`（JSON 视图）
  - `.graph-crud-modal`（CRUD 模态）
  - `.graph-empty-state`（空状态卡片）

## 5. UI 设计

### 5.1 顶部布局（固定）

```
┌─ Graph ─────────────────────────[+] [↻] [⋯] ┐
│ [Graph] [Table] [JSON]      🔍 Search...    │
├──────────────────────────────────────────┤
│  <当前 tab 的内容>                       │
├──────────────────────────────────────────┤
│  Nodes: 12   Relationships: 18   ⚠ Mock  │
└──────────────────────────────────────────┘
```

- 后端类型徽章在右下：`✓ Neo4j`（绿色）或 `⚠ Mock`（橙色）
- `[+]`：打开创建节点 modal
- `[↻]`：刷新 schema
- `[⋯]`：更多操作（清空图库、加载示例、导出 JSON）

### 5.2 Graph tab

- Cytoscape canvas 占满
- 右上角浮动工具条：fit / zoom-in / zoom-out / layout（COSE / Breadthfirst / Concentric）/ export PNG

### 5.3 Table tab

- sub-tab：`[Nodes | Relationships]`
- 每行右侧操作：编辑、删除、定位到 Graph

### 5.4 JSON tab

- 左 30%：节点 / 关系树
- 右 70%：选中项 pretty JSON + 复制 + 下载

### 5.5 空状态（Mock 且库为空时）

大块引导卡片居中显示：
- 标题：「图库为空」
- 副标题：「当前后端为 Mock 模式，暂无数据。加载一份 ZK 运维示例图谱（Host / Service / Incident / Runbook）即可上手。」
- 主按钮：「一键加载示例」（调用 `/api/graph/seed`）
- 次按钮：「手动创建第一个节点」（打开 CRUD modal）

### 5.6 示例图谱（`seed_sample` 内容）

| 节点类型 | 示例 | 关系 |
|---|---|---|
| Host | web-01, db-01, cache-01 | Host→Host（DEPENDS_ON） |
| Service | nginx, postgres, redis | Service→Host（RUNS_ON） |
| Incident | INC-001（nginx 502 突发） | Incident→Service（AFFECTS） |
| Runbook | RB-001（重启 nginx 步骤） | Runbook→Service（APPLIES_TO） |

共 8-12 节点、10-15 关系，足以展示典型运维场景。

## 6. 错误处理 / 测试

### 6.1 后端

- 现有 `tests/test_graph_api.py` 中所有断言保持通过；新增包装层后新增对应断言
- 新增 `tests/test_graph_mock.py`：覆盖 SQLite 实现所有方法（Cypher-free，CI 友好）
- 新增 `tests/test_graph_neo4j.py`：用 Cypher fixture 验证生成的 Cypher 字符串（不连真实 Neo4j）

### 6.2 前端

- 新增 `tests/test_graph_main.spec.js`：vitest + jsdom，覆盖：
  - tab 切换
  - 搜索响应解析（修 API 解析 bug）
  - CRUD 调用
  - empty state 显示
  - 健康探测失败时降级到 Mock

### 6.3 启动自检

- `server.py` 启动时调用一次 `store.health()`，若 `backend == "mock"` 写入一条 WARN 日志提示运维：「当前图库使用 Mock 存储，数据持久化在 `data/graph.sqlite`」

## 7. 范围之外（不做）

- 不做权限分级（所有登录用户可读写，沿用 2026-06-29 设计）
- 不做图谱版本管理 / 撤销栈
- 不做批量导入 / 导出（除 JSON 单文件下载）
- 不做实时协作（多用户同时编辑）
- 不做自定义属性类型校验（properties 统一存为 JSON 字符串）

## 8. 实施顺序

1. 存储层重构：`graph_store.py` 接口 + `graph_mock.py` 实现 + `graph_neo4j.py` 迁移 + `graph.py` 瘦壳化
2. API 修复：Cypher `*1..$depth`、包装层、健康端点、seed 端点
3. 前端模块拆分：`graph_main.js` 重写 + 三视图 + CRUD modal
4. `index.html` / `style.css` 更新 + 清理死代码
5. 测试：现有测试通过 + 新增 mock / cypher / 前端单测
6. 手动验证：开发模式下启动 → 打开 Graph 面板 → 加载示例 → 切换 tab → CRUD 一次

每步提交一次，便于回滚。