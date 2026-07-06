# ZK 运维智能体 - 版本变更日志

## [v1.1.1] — 2026-07-06

### Added

- ZKREQ-120: 审计日志详情展示每次 LLM 调用输入 Token 数及完整输入摘要 — `TurnTimer` 新增 `prompt_tokens_getter` / `summary_getter`，按 LLM 阶段实时捕获 `session_prompt_tokens` 增量，从会话消息中动态构建含系统提示、历史对话、工具结果的完整输入摘要
- ZKREQ-121: 审计日志 `ordered_calls` 字段记录每次 LLM 和工具调用的明细（耗时、输入 token 数、输入摘要、命令摘要），导出 CSV 新增 `ordered_calls`、`tools`、`input_tokens`、`input_summary` 列
- ZKREQ-122: 版本发布历史弹窗（changelog dialog）界面优化 — 卡片式布局、分类色条（新增/变更/修复）、搜索关键词高亮、i18n 中文化

### Changed

- ZKREQ-123: CSV 导出表头中文化（"输入Token数"、"调用明细(JSON)" 等），改用 `QUOTE_ALL` 确保 JSON 列在 Excel 中完整保留
- ZKREQ-124: 静态文件缓存策略改为 `max-age=0, must-revalidate`，开发时修改 CSS/JS 即时生效，不再受 5 分钟缓存影响

### Fixed

- ZKREQ-125: Knowledge Office 导入图片被包裹在 ``` 代码块内无法渲染 — `_knowledgeReplaceMarkdownImages` 增加代码块感知，自动将 `<img>` 移出代码块
- ZKREQ-126: 版本发布历史弹窗 DOM 层级修复 — kanban task modal 嵌套移出 changelog dialog 内部；changelog CSS 加载/滚动失效修复

## [v1.1.0] — 2026-06-29

### Added

- ZKREQ-113: License 激活管理模块 — 服务端 `api/license.py` 核心模块（AES-256-CBC 加密/解密、platform_id 与 mac_hash 生成、license 文件导入验证），`/api/license/*` 和 `/api/admin/license/*` 路由
- ZKREQ-114: License 独立激活页面 — 未激活时服务端直接返回自包含 HTML 页面（内联 CSS+JS），显示平台 ID 和 MAC 地址，支持 License 文件上传导入

### Changed

- ZKREQ-115: 服务端 License 中间件 `_require_license` — 所有非 License API 请求强制校验，无效时返回 403 中文错误提示（未激活/已过期/已拷贝/未初始化）
- ZKREQ-116: 前端 License 校验增强 — 页面加载（boot.js 安全网 + panels.js）、每次面板切换（switchPanel 入口）均校验 License，校验失败显示全屏遮罩
- ZKREQ-117: License 密钥存储路径从 `HERMES_HOME/.license` 迁移到 `DEFAULT_WORKSPACE/.license`，项目根目录 `.secret_key` 作为固定主密钥随代码部署
- ZKREQ-118: License 相关日志和错误提示中文化（`[license]` 前缀日志全部中文、API 返回错误消息中文）

### Fixed

- ZKREQ-119: 修复 `require()` 函数返回值始终为 `None` 的 Bug（`require` 只验证不返回值），影响 License 导入和生成路由

## [v1.0.3] — 2026-06-10

### Added

- ZKREQ-107: 日志分析结果支持 `hermes-log://context` 引用，点击后由 WebUI 后端通过受控 expect 登录服务器读取日志上下文
- ZKREQ-108: 新增 `/api/log-context`，按 `source/path/line/before/after` 返回日志前后文，强制配置源、路径白名单、行数上限、响应大小上限和审计记录
- ZKREQ-109: `/api/log-context` 入参支持 `host_ip/account`，后端从服务端主机清单或固定 lookup 脚本解析日志账号和密码环境变量，不接受前端明文密码
- ZKREQ-110: 日志上下文主机凭据解析新增 Neo4j 图库回退，按 `Host.ip` 查询 `ssh_user`、`ssh_password`、`ssh_port`，无需额外 host_inventory 配置

### Changed

- ZKREQ-111: 日志上下文弹窗交互增强 — 当前匹配行高亮（左侧彩色标识条 `border-left`、更强背景色、行号加粗高亮），新增浮动"回到当前行"按钮（滚动离开匹配行后自动显示，点击平滑滚动回当前位置），弹窗全部按钮和提示文字支持中文界面适配
- ZKREQ-112: Markdown 渲染支持 `hermes-log://context` 协议链接，Skill 输出中可直接点击跳转弹出日志上下文弹窗

## [v1.0.2] — 2026-06-10

### Changed

- ZKREQ-105: Knowledge Markdown / Office / ZIP 导入大小上限放宽到 500MB，并支持通过 `HERMES_WEBUI_KNOWLEDGE_IMPORT_MAX_MB` 覆盖

### Fixed

- ZKREQ-106: 审计中心补全访问 IP 记录，HTTP 请求和对话审计均优先记录 `X-Forwarded-For`，其次 `X-Real-IP`，最后回退到客户端 socket 地址

## [v1.0.1] — 2026-06-10

### Added

- ZKREQ-099: Knowledge 批量 ZIP 导入（Markdown / Office / 图片资源包，支持逐文件失败明细）
- ZKREQ-100: Knowledge 导入附件自动归档（Markdown 本地图片、Obsidian 图片链接、Office 内嵌图片统一写入 `_attachments/<note-stem>/`）
- ZKREQ-101: Knowledge Markdown / Office 导入 data URI 图片自动落盘并改写为相对附件链接

### Changed

- ZKREQ-102: Knowledge 上传 Markdown、导入 Office、批量导入 ZIP、编辑器插入图片改为页面内隐藏文件选择器，修复部分浏览器点击无响应
- ZKREQ-103: Knowledge 导入和笔记文件操作错误提示中文化，批量导入失败时展示可读的逐文件诊断

### Fixed

- ZKREQ-104: Workspace 文件树清理异常展开状态，并检测递归目录和过深嵌套，避免复制运行中 session 到新标签页时页面卡死

## [v1.0.0] — 2026-04-30

### Added

- ZKREQ-001: 一键部署包（Docker 镜像 + 部署脚本）
- ZKREQ-002: agent-browser 离线部署（npm + Chromium，177MB）
- ZKREQ-003: hermes-full-deploy 完整包（镜像 + 源码 + 脚本，2GB）
- ZKREQ-004: .env 配置分离（MINIMAX API Key / WebUI 密码等）
- ZKREQ-006: Windows 桌面客户端部署（hermes-desktop Electron 原生应用）
- ZKREQ-007: 安全约束规则（Tirith 内置安全层，禁用所有删除操作）
- ZKREQ-010: 故障日志分析 Skill（log_analysis v1.2.0，Markdown 报告）
- ZKREQ-011: Shell 巡检 Skill（8 个检测场景，Markdown 报告）
- ZKREQ-012: API 巡检 Skill（HTTP 探活检测，H1-H5 验证）
- ZKREQ-016: Web 巡检 Skill（Web 页面可用性、性能巡检，W1-W7 检测矩阵）
- ZKREQ-020: Obsidian 本地笔记库接入
- ZKREQ-022: Neo4j 图数据库部署（neo4j:5，588MB）
- ZKREQ-023: Neo4j 部署集成到一键脚本
- ZKREQ-050: 服务器端 CLI（`hermes` 命令包装脚本）
- ZKREQ-083: Skill 开发自动化 Skill（一次问答完成 Skill 开发全流程）
- ZKREQ-090: 安全审计模块（用户操作全量留痕，Web 管理 + Excel 导出）
- ZKREQ-091: 审计日志采集（访问时间 / 时间戳 / 客户端 IP / 会话 ID / 问答内容 / 浏览器 UA）
- ZKREQ-092: 审计日志存储（按天分表 .jsonl，目录独立隔离，全量永久留痕）
- ZKREQ-093: Web 多条件检索（IP / 会话ID / 关键词模糊搜索，日期范围筛选）
- ZKREQ-094: Web 分页浏览（时间倒序，上下翻页，总页数统计）
- ZKREQ-095: Web 日志详情（弹窗查看完整问答原文，保留原始换行格式）
- ZKREQ-096: Excel/CSV 导出（筛选导出，中文不乱码，自动带日期文件名）
- ZKREQ-097: 左上角常驻版本徽标（v1.0.0），点击触发发布历史弹窗
- ZKREQ-098: 版本发布历史弹窗，支持搜索 / 过滤，数据来源 ZK_CHANGELOG.md
