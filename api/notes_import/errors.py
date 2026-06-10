from __future__ import annotations


class ImportStageError(ValueError):
    """Validation error with a stable import stage for batch reporting."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


_EXACT_ERROR_MESSAGES = {
    "batch import requires a .zip archive": "批量导入需要上传 .zip 压缩包",
    "invalid zip archive": "ZIP 压缩包无效或已损坏",
    "duplicate archive member path": "ZIP 内存在重复文件路径",
    "archive contents exceed import size limit": "ZIP 解压后的总大小超过导入限制",
    "unsupported file type in batch import": "不支持的文件类型；批量导入仅支持 Markdown、Office 文档，以及被 Markdown 引用的图片",
    "archive member path is empty or invalid": "ZIP 内文件路径为空或无效",
    "absolute archive paths are not allowed": "ZIP 内不允许使用绝对路径",
    "archive member path is empty": "ZIP 内文件路径为空",
    "archive path traversal is not allowed": "ZIP 内文件路径不能包含 ..",
    "invalid local image path": "Markdown 本地图片路径无效",
    "local image path escapes archive root": "Markdown 本地图片路径不能跳出 ZIP 根目录",
    "Office import requires the optional markitdown package": "Office 导入需要安装可选依赖 markitdown",
    "Office conversion produced empty Markdown": "Office 转换后没有生成 Markdown 内容",
    "note already exists": "目标笔记已存在",
    "directory already exists": "目标目录已存在",
    "directory is not empty": "目录非空",
    "note not found": "笔记不存在",
    "directory not found": "目录不存在",
    "media not found": "图片附件不存在",
    "path is required": "路径不能为空",
    "invalid path": "路径无效",
    "path traversal is not allowed": "路径不能包含 ..",
    "hidden vault paths are not accessible": "隐藏目录或系统目录不可访问",
    "only Markdown notes are supported": "仅支持 Markdown 笔记",
    "only .md files can be uploaded": "仅支持上传 .md 或 .markdown 文件",
    "only image assets are supported": "仅支持图片附件",
    "only image media can be served": "仅支持预览图片附件",
    "only docx, xlsx, and pptx imports are supported": "仅支持导入 docx、xlsx、pptx 文件",
    "title is required": "标题不能为空",
    "category must be a directory": "分类必须是目录",
    "target_dir must be a directory": "导入目标必须是目录",
    "parent must be a directory": "父级必须是目录",
    "parent must be an existing directory": "父级目录必须已存在",
    "invalid directory name": "目录名称无效",
    "vault root cannot be modified": "不能直接修改知识库根目录",
    "attachment directories are managed automatically": "附件目录由系统自动管理",
    "directory cannot be moved into itself": "目录不能移动到自身内部",
}


def friendly_error(message: str) -> str:
    raw = str(message or "").strip()
    if not raw:
        return "导入失败"
    if raw in _EXACT_ERROR_MESSAGES:
        return _EXACT_ERROR_MESSAGES[raw]
    if raw.startswith("local image not found:"):
        path = raw.split(":", 1)[1].strip()
        return f"本地图片未找到：{path}"
    if raw.startswith("File too large (max ") and raw.endswith("MB)"):
        size = raw.removeprefix("File too large (max ").removesuffix("MB)")
        return f"文件过大，最大 {size} MB"
    if raw == "No file field in request":
        return "请求中没有文件字段"
    if raw == "No archive field in request":
        return "请求中没有 ZIP 文件字段"
    return raw


def failure_dict(source: str, exc: Exception, default_stage: str = "import") -> dict:
    stage = getattr(exc, "stage", None) or default_stage
    return {
        "source": str(source or ""),
        "stage": str(stage or default_stage),
        "error": friendly_error(str(exc) or exc.__class__.__name__),
    }
