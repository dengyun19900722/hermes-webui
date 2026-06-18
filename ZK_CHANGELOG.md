# ZK 运维智能体 - 版本变更日志

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
