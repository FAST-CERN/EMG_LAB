"""Help window chapter wiring and renderer selection (offscreen-safe)."""
import os
import re
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets as W

from emg_lab.help import (ASSETS, PAGE_TEMPLATE, GuidePage, TextHelpBrowser,
                          _assets_complete, _chapter_html, _webengine_available)
from emg_lab.storage import ROOT


def _app():
    return W.QApplication.instance() or W.QApplication([])


def test_offscreen_selects_text_fallback():
    app = _app()
    if app.platformName() != 'offscreen':
        return  # 本测试只在 offscreen 会话下有意义
    assert _webengine_available() is False
    page = GuidePage(ROOT / 'docs' / 'TECHNICAL_GUIDE.md')
    assert isinstance(page.browser, TextHelpBrowser)


def test_chapters_split_and_search_still_work():
    _app()
    page = GuidePage(ROOT / 'docs' / 'TECHNICAL_GUIDE.md')
    titles = [title for title, _ in page.chapters]
    assert any('系统整体链路' in title for title in titles)
    page.filter_chapters('Mermaid 渲染失败')  # 模板内容不应出现在章节里
    assert page.contents.count() == 0
    page.filter_chapters('训练')
    assert page.contents.count() >= 1


def test_chapter_payload_cannot_break_out_of_script_tag():
    malicious = '正文 ```mermaid\nflowchart TD\n a["</script><img src=x>"] --> b\n```\n'
    html = _chapter_html(malicious)
    assert '__PAYLOAD__' not in html
    assert '<\\/script>' in html  # JSON 内的 </ 已转义，无法提前闭合 script


def test_highlightjs_assets_bundled():
    # hljs 三件套随包：common 包、powershell 语言包、github 浅色主题
    for name in ('highlight.min.js', 'highlight-powershell.min.js',
                 'highlight-github.min.css'):
        assert (ASSETS / name).is_file()


def test_template_references_highlightjs():
    assert '<link rel="stylesheet" href="highlight-github.min.css">' in PAGE_TEMPLATE
    assert '<script src="highlight.min.js"></script>' in PAGE_TEMPLATE
    assert '<script src="highlight-powershell.min.js"></script>' in PAGE_TEMPLATE


def test_asset_gate_covers_highlightjs(tmp_path, monkeypatch):
    from emg_lab import help as help_mod
    for name in ('marked.min.js', 'mermaid.min.js'):
        (tmp_path / name).write_bytes(b'x')
    monkeypatch.setattr(help_mod, 'ASSETS', tmp_path)
    assert _assets_complete() is False  # hljs 任一文件缺失，整窗不放行 WebEngine
    for name in help_mod.ASSET_FILES:
        (tmp_path / name).write_bytes(b'x')
    assert _assets_complete() is True


def test_badge_and_highlight_rules_in_template():
    # 徽标 = 围栏语言原文透传；text/plain 家族视为无语言：不徽标、不高亮
    assert 'data-lang' in PAGE_TEMPLATE
    plain = {w.strip().strip("'\"") for w in
             re.search(r"var PLAIN = \[([^\]]*)\];", PAGE_TEMPLATE).group(1).split(',')}
    assert {'text', 'text/plain', 'plaintext', 'txt'} <= plain
    # mermaid 围栏显式跳过徽标（整体交给图表渲染），不靠处理顺序
    assert "key === 'mermaid'" in PAGE_TEMPLATE
    # 高亮只对收录语言（python/json/powershell 及别名）调用 hljs
    hl = {w.split(':')[0].strip() for w in
          re.search(r"var HIGHLIGHT = \{([^}]*)\};", PAGE_TEMPLATE).group(1).split(',')
          if ':' in w}
    assert hl == {'python', 'py', 'json', 'powershell', 'ps', 'ps1'}


def test_help_css_cards_code_and_wraps_long_lines():
    css = (ASSETS / 'help.css').read_text(encoding='utf-8')
    assert 'pre[data-lang]' in css  # 语言徽标样式
    assert 'pre-wrap' in css  # 长行自动换行，不出横向滚动
