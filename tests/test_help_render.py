"""Help window chapter wiring and renderer selection (offscreen-safe)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets as W

from emg_lab.help import GuidePage, TextHelpBrowser, _chapter_html, _webengine_available
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
