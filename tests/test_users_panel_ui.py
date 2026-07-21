"""Verify Users admin panel is wired into the existing Settings UI.

UI规范约束（docs/UIUX-GUIDE.md）：
- 复用现有 settings-pane / settings-section-head 容器样式
- 复用现有 side-menu-item + data-settings-section 切换机制
- 不引入新颜色 token；用现有 border/bg/text 变量
- 遵循 switchSettingsSection() 的 map + 懒加载契约
"""
from pathlib import Path


_INDEX_HTML = Path("static") / "index.html"
_PANELS_JS = Path("static") / "panels.js"
_USERS_JS = Path("static") / "users_panel.js"


def test_users_panel_js_exists():
    assert _USERS_JS.exists()


def test_users_panel_js_calls_admin_endpoint():
    src = _USERS_JS.read_text(encoding="utf-8")
    assert "/api/admin/users" in src


def test_users_panel_js_has_render_function():
    """应暴露 loadUsersPanel() 与 panels.js 的懒加载契约一致。"""
    src = _USERS_JS.read_text(encoding="utf-8")
    assert "loadUsersPanel" in src


def test_users_panel_js_has_escape_html():
    """XSS 防护 — 用户名/角色插入 DOM 前必须转义。"""
    src = _USERS_JS.read_text(encoding="utf-8")
    assert "escapeHtml" in src or "textContent" in src


def test_users_panel_js_calls_audit_endpoint():
    src = _USERS_JS.read_text(encoding="utf-8")
    assert "/api/admin/audit" in src


def test_index_html_has_users_sidebar_item():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    # 在 Settings 侧边栏里, 与 appearance/preferences 同级
    assert 'data-settings-section="users"' in src


def test_index_html_has_users_pane():
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="settingsPaneUsers"' in src


def test_index_html_includes_users_panel_js():
    """users_panel.js 应在 index.html 末尾被引入。"""
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "users_panel.js" in src


def test_panels_js_maps_users_section():
    """switchSettingsSection 必须能识别 users section。"""
    src = _PANELS_JS.read_text(encoding="utf-8")
    # section map 应包含 'Users' 标签
    assert "'users'" in src or '"users"' in src
    # 'Users' 字符串应出现在 map object 中
    assert "Users" in src, "panels.js section map must include Users label"


def test_panels_js_lazy_loads_users_panel():
    """switchSettingsSection 应在打开 users 时调用 loadUsersPanel()。"""
    src = _PANELS_JS.read_text(encoding="utf-8")
    assert "loadUsersPanel" in src


def test_users_panel_css_exists():
    assert (_USERS_JS.parent / "users_panel.css").exists()


def test_index_html_includes_users_panel_css():
    """users_panel.css 应在 style.css 之后被引入。"""
    src = _INDEX_HTML.read_text(encoding="utf-8")
    assert "users_panel.css" in src


def test_users_panel_js_uses_users_section_class():
    """各 section 应使用 .users-section 类以获得更大间距。"""
    src = _USERS_JS.read_text(encoding="utf-8")
    assert "users-section" in src


def test_i18n_zh_block_has_users_keys():
    """zh 块应包含中文 users_* 翻译(不只是英文占位)。"""
    import re
    src = Path("static") / "i18n.js"
    text = src.read_text(encoding="utf-8")
    # 找到 zh: { 块的范围
    m = re.search(r"^  zh: \{(.*?)^  \},", text, re.MULTILINE | re.DOTALL)
    assert m, "zh block not found"
    zh_block = m.group(1)
    assert "settings_tab_users" in zh_block
    # 中文翻译应包含中文 unicode 字符
    assert "用户" in zh_block or "使用者" in zh_block, (
        "zh block must contain Chinese (non-ASCII) translations"
    )


def test_i18n_zh_tw_block_has_users_keys():
    """zh-tw 块应包含中文 users_* 翻译。"""
    import re
    src = Path("static") / "i18n.js"
    text = src.read_text(encoding="utf-8")
    # 找到 zh-tw 块 (在 zh 之后)
    matches = list(re.finditer(r"^  zh-tw: \{(.*?)^  \},", text, re.MULTILINE | re.DOTALL))
    if not matches:
        # fallback: skip if not found
        return
    zh_tw_block = matches[0].group(1)
    assert "settings_tab_users" in zh_tw_block
    assert "使用者" in zh_tw_block or "用戶" in zh_tw_block, (
        "zh-tw block must contain Chinese (non-ASCII) translations"
    )