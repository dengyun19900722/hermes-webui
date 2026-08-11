# 图库管理可视化模块设计规格

## 1. 概述

为 Hermes Web UI 增加 **Graph 图库管理面板**，支持对 Neo4j 中运维知识图谱进行可视化浏览、搜索、增删改查和拓扑查看。

### 1.1 核心特性

| 功能 | 说明 |
|------|------|
| 节点浏览 | 按类型浏览节点，支持分页，支持全类型动态发现 |
| 关系可视化 | 节点-关系图形化展示（Force-directed 布局） |
| 拓扑视图 | 分区分层布局，支持过滤，可点击钻取 |
| 列表视图 | 传统表格视图，支持搜索和批量操作 |
| 搜索 | 按名称/类型/标签搜索节点和关系 |
| 详情面板 | 点击节点/关系查看完整属性 |
| 增删改查 | 节点和关系的创建、编辑、删除全功能支持 |
| Schema 动态同步 | Neo4j 侧新增/修改节点类型，页面实时同步，无需硬编码 |

### 1.2 关键设计决策

- **数据层**：后端 FastAPI 代理层连接 Neo4j（neo4j Python Driver），前端不直连数据库
- **凭证管理**：Neo4j 连接信息通过环境变量配置（`NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`）
- **图模型动态化**：节点类型、关系类型、属性模板均从 Neo4j 实时发现，不硬编码
- **三视图模式**：图形 / 拓扑 / 列表，三种视图共享同一数据源，通过模式切换切换
- **权限控制**：暂不涉及权限，所有登录用户可读写图库
- **部署方式**：集成到 Hermes WebUI 作为内置页面，与 Knowledge 面板平级

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Hermes WebUI                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Graph Panel（新）                                          │  │
│  │  ┌─────────────┬──────────────────────────────────────┐  │  │
│  │  │ 左侧边栏      │ 主画布区域（三种模式切换）                    │  │  │
│  │  │ · 类型筛选器   │ [图形] Force-directed 布局              │  │  │
│  │  │ · 搜索框      │ [拓扑] 分区分层布局 + 过滤               │  │  │
│  │  │ · 节点列表分页 │ [列表] 表格视图 + 排序                  │  │  │
│  │  │ · 详情预览    │                                        │  │  │
│  │  └─────────────┴──────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI 代理层 (api/graph.py)                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Schema 动态发现  │  节点 CRUD  │  关系 CRUD  │  搜索  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                     neo4j Python Driver                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                         Bolt 协议
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Neo4j 数据库（已有实例）                        │
│  环境变量: NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型

### 3.1 动态 Schema 发现

通过 Cypher 查询实时发现，不硬编码：

```cypher
-- 发现所有节点标签
CALL db.labels() YIELD label RETURN label

-- 发现所有关系类型
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType

-- 发现某标签的所有属性
MATCH (n:{label}) RETURN keys(n) LIMIT 1
```

### 3.2 节点结构

```json
{
  "id": "node-uuid",
  "labels": ["Service"],
  "properties": {
    "name": "支付服务",
    "category": "核心业务",
    "status": "running",
    "labels": ["关键", "金融"],
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

- `id`：Neo4j 内部 Element ID（字符串形式）
- `labels`：节点类型标签列表（支持多标签）
- `properties`：自由扩展的键值对，前端不假设任何固定属性字段
- 所有节点共享 `labels` 数组属性（用于标签筛选）

### 3.3 关系结构

```json
{
  "id": "rel-uuid",
  "type": "DEPLOYED_ON",
  "start_node_id": "node-uuid-1",
  "end_node_id": "node-uuid-2",
  "start_node_name": "支付服务",
  "end_node_name": "主机-01",
  "properties": {
    "weight": 1,
    "labels": []
  }
}
```

### 3.4 三种视图模式

| 视图 | 布局算法 | 适用场景 |
|------|---------|---------|
| **图形模式** | Force-directed（引力-斥力模型）| 探索节点间关系，发现聚类 |
| **拓扑模式** | Hierarchical / Tree（分层布局）| 展示服务依赖链，钻取查看 |
| **列表模式** | 表格排序 + 分页 | 精确搜索、批量管理 |

---

## 4. API 设计

### 4.1 Schema 接口

**GET `/api/graph/schema`**

返回图谱的动态结构：

```json
{
  "node_labels": ["Service", "Host", "Component", "Alert", "FAQ"],
  "relationship_types": ["DEPLOYED_ON", "DEPENDS_ON", "CALLS", "CAUSES", "RELATED_TO", "MONITORS"],
  "stats": {
    "Service": 120,
    "Host": 45,
    "Component": 300,
    "Alert": 890,
    "FAQ": 25
  }
}
```

### 4.2 节点接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/graph/nodes` | 列表查询（支持 type 过滤、分页、关键词搜索） |
| POST | `/api/graph/nodes` | 创建节点 |
| GET | `/api/graph/nodes/<id>` | 节点详情 |
| PUT | `/api/graph/nodes/<id>` | 更新节点（属性） |
| DELETE | `/api/graph/nodes/<id>` | 删除节点（同时删除关联关系） |
| POST | `/api/graph/nodes/<id>/expand` | 钻取：返回指定深度内的关联节点和关系 |

**GET `/api/graph/nodes` 查询参数：**

```
?type=Service           # 按节点标签过滤
&page=1                 # 页码（从 1 开始）
&page_size=50           # 每页条数（默认 50，上限 200）
&q=支付                 # 关键词搜索（匹配 name/properties 中的字符串值）
```

**GET `/api/graph/nodes` 响应：**

```json
{
  "nodes": [
    {
      "id": "abc123",
      "labels": ["Service"],
      "name": "支付服务",
      "properties": { "category": "核心业务", "status": "running", "labels": ["关键"] },
      "created_at": null
    }
  ],
  "total": 120,
  "page": 1,
  "page_size": 50,
  "has_more": true
}
```

**POST `/api/graph/nodes` 请求：**

```json
{
  "labels": ["Service"],
  "properties": {
    "name": "新服务",
    "category": "测试",
    "labels": []
  }
}
```

**POST `/api/graph/nodes/<id>/expand` 请求：**

```json
{
  "depth": 1,
  "direction": "both",
  "relationship_types": ["DEPENDS_ON", "DEPLOYED_ON"]
}
```

**POST `/api/graph/nodes/<id>/expand` 响应：**

```json
{
  "center": { "id": "abc", "labels": ["Service"], "name": "支付服务", "properties": {} },
  "nodes": [
    { "id": "def", "labels": ["Component"], "name": "数据库", "properties": {} }
  ],
  "relationships": [
    { "id": "rel1", "type": "DEPENDS_ON", "start_node_id": "abc", "end_node_id": "def", "properties": {} }
  ]
}
```

### 4.3 关系接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/graph/relationships` | 列表查询（支持分页、过滤） |
| POST | `/api/graph/relationships` | 创建关系 |
| GET | `/api/graph/relationships/<id>` | 关系详情 |
| PUT | `/api/graph/relationships/<id>` | 更新关系属性 |
| DELETE | `/api/graph/relationships/<id>` | 删除关系 |

**POST `/api/graph/relationships` 请求：**

```json
{
  "type": "DEPENDS_ON",
  "start_node_id": "abc",
  "end_node_id": "def",
  "properties": {
    "weight": 1,
    "labels": []
  }
}
```

### 4.4 拓扑和搜索接口

**GET `/api/graph/topology`**

返回拓扑视图数据，支持按节点类型分区：

```
?depth=2                # 钻取深度
&center_id=abc          # 中心节点 ID
&node_types=Service,Host # 筛选显示的节点类型
&rel_types=DEPENDS_ON   # 筛选显示的关系类型
```

**GET `/api/graph/search`**

全局搜索，匹配节点名称和属性：

```
?q=支付&types=Service,Alert&limit=20
```

---

## 5. 前端模块设计

### 5.1 面板入口

- 在左侧导航栏新增 **Graph** 按钮（与 Knowledge 平级）
- 路由：Graph 面板复用现有面板切换机制（参考 `panels.js` 的 `switchPanel` 模式）
- 首次加载时调用 `GET /api/graph/schema` 获取节点类型统计

### 5.2 左侧边栏

```
┌─────────────────┐
│ 🔍 搜索框        │
├─────────────────┤
│ 类型筛选器        │
│ ☑ Service (120) │
│ ☑ Host (45)     │
│ ☐ Component     │
│ ☐ Alert         │
│ ☐ FAQ           │
├─────────────────┤
│ 节点列表（分页）   │
│ · 支付服务        │
│ · 认证服务        │
│ · 主机-01        │
│ ...             │
└─────────────────┘
```

- 搜索框：300ms 防抖，调用 `/api/graph/search`
- 节点列表：支持点击选中，高亮对应图形节点
- 选中节点：右侧展示详情面板

### 5.3 主画布区域

三种模式，通过 Tab 切换：

```
[图形] [拓扑] [列表]
```

**图形模式（默认）：**

- Cytoscape.js Force-Directed 布局
- 节点颜色按类型区分（Service=蓝 / Host=绿 / Component=橙 / Alert=红 / FAQ=紫）
- 支持缩放（鼠标滚轮）、拖拽（拖动空白区域）、框选（框选多个节点）
- 点击节点：选中节点 + 侧边栏高亮 + 详情面板展示
- 悬停节点：显示名称标签
- 双击节点：触发 expand 钻取

**拓扑模式：**

- Hierarchical 分层布局（根部节点在上或左）
- 按节点类型分区展示（可折叠/展开分区）
- 顶部过滤器栏：类型筛选、关系类型筛选
- 点击节点：选中 + 钻取展开
- 支持缩放和平移

**列表模式：**

- 表格列：名称 | 类型 | 状态 | 标签 | 操作
- 支持列排序（点击表头切换升序/降序）
- 操作列：查看 / 编辑 / 删除
- 底部：分页控件（首页 / 上一页 / 页码 / 下一页 / 末页）

### 5.4 详情面板

点击节点或关系后，从右侧滑出详情面板：

```
┌──────────────────────────────┐
│ 节点详情               [X]  │
├──────────────────────────────┤
│ 类型: Service               │
│ 名称: 支付服务               │
│ 状态: running               │
│ 标签: [关键] [金融]          │
├──────────────────────────────┤
│ 属性                        │
│ ┌──────────────────────────┐ │
│ │ category: 核心业务         │ │
│ │ version: 2.1.0           │ │
│ │ owner: ops-team          │ │
│ └──────────────────────────┘ │
├──────────────────────────────┤
│ 关联关系 (5)                 │
│ · DEPENDS_ON → 数据库        │
│ · DEPLOYED_ON → 主机-01     │
│ · CALLS → 订单服务           │
├──────────────────────────────┤
│ [编辑] [删除] [钻取]         │
└──────────────────────────────┘
```

- 编辑：弹出模态框编辑属性（属性名可自由添加/修改/删除）
- 删除：二次确认后删除
- 钻取：调用 expand 接口，图形模式下追加节点到画布

### 5.5 新建节点 / 新建关系 模态框

**新建节点：**

```
┌──────────────────────────────┐
│ 新建节点                 [X] │
├──────────────────────────────┤
│ 节点类型: [Service    ▼]     │
│                                │
│ 属性:                         │
│ 名称:     [支付服务        ]  │
│ category: [核心业务        ]  │
│ status:   [running       ]   │
│ [+ 添加属性]                  │
│                                │
│ 标签:     [关键, 金融     ]  │
│           (逗号分隔)           │
├──────────────────────────────┤
│            [取消] [创建]      │
└──────────────────────────────┘
```

**新建关系：**

```
┌──────────────────────────────┐
│ 新建关系                 [X] │
├──────────────────────────────┤
│ 关系类型: [DEPENDS_ON   ▼]   │
│                                │
│ 起始节点: [支付服务         ] │
│ 结束节点: [数据库           ] │
│ (支持搜索下拉)                │
│                                │
│ 属性:                         │
│ weight:   [1              ]   │
│ [+ 添加属性]                  │
├──────────────────────────────┤
│            [取消] [创建]      │
└──────────────────────────────┘
```

---

## 6. 后端模块设计

### 6.1 文件结构

```
api/
  graph.py          # Neo4j 连接 + 所有图谱 API 逻辑
  routes.py          # 路由分发（增加 graph 路由注册）
```

### 6.2 Neo4j 连接管理

```python
# 环境变量
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Driver 单例（线程安全）
_driver = None

def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver
```

### 6.3 分页策略

- 列表查询使用 Cypher `SKIP / LIMIT`，避免全表扫描
- count 查询使用 `COUNT()` 聚合
- 大图谱展示使用 expand 渐进加载，不做全量 fetch

### 6.4 错误处理

- Neo4j 连接失败：返回 503 Service Unavailable，错误信息不泄露数据库细节
- 节点/关系不存在：返回 404
- 创建/更新时属性类型不支持（如列表嵌套）：返回 400 并提示
- 所有异常写入日志，不返回 traceback 到前端

---

## 7. 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 连接 URI |
| `NEO4J_USER` | `neo4j` | 用户名 |
| `NEO4J_PASSWORD` | `（空）` | 密码 |
| `HERMES_WEBUI_GRAPH_POLL_INTERVAL` | `30` | 前端轮询间隔（秒），0 表示禁用轮询 |

---

## 8. 实现计划

分 4 步实现，每步可独立验证：

### Phase 1：环境准备 + 后端骨架
- [ ] 环境变量配置读取（`api/config.py` 增加 graph 相关配置）
- [ ] `api/graph.py` 骨架：Neo4j Driver 单例、Schema 发现接口
- [ ] 路由注册（`api/routes.py` 接入 `/api/graph/*`）
- [ ] 基础单元测试

### Phase 2：前端 Graph 面板入口
- [ ] 导航入口：左侧导航栏 Graph 按钮（参考 Knowledge 入口）
- [ ] 面板骨架：三种视图 Tab + 左侧边栏布局
- [ ] Schema 接口调用 + 类型筛选器渲染
- [ ] 节点列表分页（列表模式）

### Phase 3：图形可视化组件
- [ ] Cytoscape.js 集成（图形模式）
- [ ] 拓扑模式分层布局
- [ ] 节点点击 / 悬停交互
- [ ] 详情面板滑出
- [ ] expand 钻取逻辑

### Phase 4：搜索 + CRUD + 完整链路
- [ ] 搜索接口（后端 + 前端）
- [ ] 新建/编辑/删除节点模态框
- [ ] 新建/编辑/删除关系模态框
- [ ] 完整链路集成测试

---

## 9. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 图渲染引擎 | Cytoscape.js | 成熟稳定，布局算法丰富，交互完善，与 Vue 3 兼容 |
| 布局算法 | force-directed（图形）+ hierarchical（拓扑）+ table（列表） | 覆盖探索和结构化展示需求 |
| 后端驱动 | neo4j-python-driver（官方） | 官方 driver，线程安全，支持事务 |
| 前端轮询 | setInterval + 防抖搜索 | 简单可靠，满足当前实时性需求 |
| 前端状态 | 组件内 local state（参考 panels.js 模式） | 图谱数据量大，不放在全局 S 状态 |

---

## 10. 已知限制

- 暂不涉及权限控制，所有用户可读写
- 暂不实现 WebSocket 实时推送，图数据变更通过轮询同步
- 暂不实现批量导入/导出
- 删除节点时级联删除关联关系（Cascade），需明确告知用户
- 节点属性完全自由扩展，前端详情面板属性展示为键值对列表，无固定字段格式化
