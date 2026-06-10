from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.resolve()
UI_JS_PATH = REPO_ROOT / "static" / "ui.js"
NOTES_JS_PATH = REPO_ROOT / "static" / "obsidian_notes.js"

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_DRIVER_SRC = r"""
const fs = require('fs');
const uiSrc = fs.readFileSync(process.argv[2], 'utf8');
const notesSrc = fs.readFileSync(process.argv[3], 'utf8');
const payload = JSON.parse(process.argv[4]);

global.window = {};
global.document = { createElement: () => ({ innerHTML: '', textContent: '' }) };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const t = s => s;
const _IMAGE_EXTS=/\.(png|jpg|jpeg|gif|webp|bmp|ico|avif)$/i;
const _SVG_EXTS=/\.svg$/i;
const _AUDIO_EXTS=/\.(mp3|ogg|wav|m4a|aac|flac|wma|opus|webm)$/i;
const _VIDEO_EXTS=/\.(mp4|webm|mkv|mov|avi|ogv|m4v)$/i;
const _PDF_EXTS=/\.pdf$/i;
const _HTML_EXTS=/\.(html|htm)$/i;
const _CSV_EXTS=/\.csv$/i;
const _EXCALIDRAW_EXTS=/\.excalidraw$/i;
const _mediaPlayerHtml = (kind, src, name) => `<${kind} src="${esc(src)}">${esc(name)}</${kind}>`;

function extractFunc(src, name) {
  const re = new RegExp('function\\s+' + name + '\\s*\\(');
  const start = src.search(re);
  if (start < 0) throw new Error(name + ' not found');
  let i = src.indexOf('{', start);
  let depth = 1; i++;
  while (depth > 0 && i < src.length) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') depth--;
    i++;
  }
  return src.slice(start, i);
}

eval([
  '_knowledgeNormalizeVaultPath',
  '_knowledgePathWithoutQueryFragment',
  '_knowledgeDecodeLinkPath',
  '_knowledgeMarkdownDestination',
  '_knowledgeIsExternalMediaDestination',
  '_knowledgeImageAltFromPath',
  '_knowledgeEncodeMediaPath',
  '_knowledgeResolveImagePath',
  '_knowledgeImageHtml',
  '_knowledgeReplaceMarkdownImages',
  '_knowledgeResolveMediaMarkdown',
].map(name => extractFunc(notesSrc, name)).join('\n'));
eval(extractFunc(uiSrc, '_matchBacktickFenceLine'));
eval(extractFunc(uiSrc, '_isBacktickFenceClose'));
eval(extractFunc(uiSrc, 'renderMd'));

const rewritten = _knowledgeResolveMediaMarkdown(payload.markdown, payload.notePath);
const html = renderMd(rewritten);
process.stdout.write(JSON.stringify({ rewritten, html }));
"""


@pytest.fixture(scope="module")
def driver_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("knowledge_media_driver") / "driver.js"
    path.write_text(_DRIVER_SRC, encoding="utf-8")
    return str(path)


def _render_knowledge_markdown(driver_path: str, markdown: str, note_path: str) -> dict:
    result = subprocess.run(
        [NODE, driver_path, str(UI_JS_PATH), str(NOTES_JS_PATH), json.dumps({"markdown": markdown, "notePath": note_path})],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node driver failed: {result.stderr}")
    return json.loads(result.stdout)


def test_imported_attachment_markdown_renders_to_note_media_image(driver_path):
    result = _render_knowledge_markdown(
        driver_path,
        "# 标题\n\n![截图](_attachments/笔记/截图.png)\n",
        "导入/文档/笔记.md",
    )

    assert '<img class="msg-media-img"' in result["html"]
    assert 'alt="截图"' in result["html"]
    assert "api/notes/media?path=" in result["html"]
    assert "%E5%AF%BC%E5%85%A5%2F%E6%96%87%E6%A1%A3%2F_attachments%2F%E7%AC%94%E8%AE%B0%2F%E6%88%AA%E5%9B%BE.png" in result["html"]


def test_obsidian_wikilink_with_spaced_attachment_path_renders(driver_path):
    result = _render_knowledge_markdown(
        driver_path,
        "![[附件/登录 截图 (1).png|登录截图]]",
        "导入/runbooks/login.md",
    )

    assert '<img class="msg-media-img"' in result["html"]
    assert 'alt="登录截图"' in result["html"]
    assert "%E5%AF%BC%E5%85%A5%2Frunbooks%2F%E9%99%84%E4%BB%B6%2F%E7%99%BB%E5%BD%95%20%E6%88%AA%E5%9B%BE%20%281%29.png" in result["html"]
