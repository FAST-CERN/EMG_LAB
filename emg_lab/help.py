"""Searchable offline help, using the same Markdown files as the developer docs.

Chapters render in a local QtWebEngine page with marked + mermaid +
highlight.js from ``emg_lab/help_assets`` (fully offline), so the Mermaid
diagrams in the guides draw as SVG and fenced code gets language badges with
python/json/powershell syntax color.  When QtWebEngine or those scripts are
unavailable — for example offscreen test runs — the same chapters fall back
to a plain QTextBrowser where Mermaid blocks show as code.
"""
from pathlib import Path
import html as html_lib
import json
import re
from PySide6 import QtCore, QtGui, QtWidgets as W

from .storage import ROOT

ASSETS = Path(__file__).resolve().parent / 'help_assets'

# 资源门禁：任一文件缺失即整窗降级 TextHelpBrowser，不开半残的 Web 页。
ASSET_FILES = ('marked.min.js', 'mermaid.min.js', 'highlight.min.js',
               'highlight-powershell.min.js', 'highlight-github.min.css')

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="highlight-github.min.css">
<link rel="stylesheet" href="help.css">
<script src="marked.min.js"></script>
<script src="mermaid.min.js"></script>
<script src="highlight.min.js"></script>
<script src="highlight-powershell.min.js"></script>
</head>
<body>
<div id="content"></div>
<script>
(function () {
  var source = __PAYLOAD__;
  var host = document.getElementById('content');
  if (typeof marked === 'undefined') {
    var pre = document.createElement('pre');
    pre.textContent = source;
    host.appendChild(pre);
    return;
  }
  host.innerHTML = marked.parse(source);

  // 语言徽标与高亮：徽标显示围栏语言原文；text/plain 家族视为无语言，
  // 不徽标不高亮；mermaid 围栏整体交给图表渲染，同样不徽标；
  // 高亮只对收录语言（python/json/powershell 及别名）生效。
  var PLAIN = ['text', 'text/plain', 'plaintext', 'txt'];
  var HIGHLIGHT = { python: 1, py: 1, json: 1, powershell: 1, ps: 1, ps1: 1 };
  host.querySelectorAll('pre > code[class*="language-"]').forEach(function (el) {
    var lang = (el.className.match(/language-(\\S+)/) || [])[1];
    if (!lang) return;
    var key = lang.toLowerCase();
    if (PLAIN.indexOf(key) !== -1 || key === 'mermaid') return;
    el.parentElement.setAttribute('data-lang', lang);
    if (typeof hljs !== 'undefined' && HIGHLIGHT[key]) hljs.highlightElement(el);
  });

  if (typeof mermaid === 'undefined') return;
  var graphs = [];
  host.querySelectorAll('code.language-mermaid').forEach(function (el) {
    var div = document.createElement('pre');
    div.className = 'mermaid';
    div.textContent = el.textContent;
    el.parentElement.replaceWith(div);
    graphs.push(div);
  });
  if (!graphs.length) return;
  mermaid.initialize({ startOnLoad: false, theme: 'default',
    fontFamily: '"Microsoft YaHei UI", "Microsoft YaHei", sans-serif' });
  mermaid.run({ nodes: graphs }).catch(function (err) {
    graphs.forEach(function (node) {
      if (node.querySelector('svg')) return;
      node.classList.add('mermaid-error');
      node.textContent = 'Mermaid 渲染失败：' + (err && err.message ? err.message : err);
    });
  });
})();
</script>
</body>
</html>
"""

try:
    from PySide6 import QtWebEngineCore, QtWebEngineWidgets
except Exception:  # pragma: no cover - PySide6 Addons missing on exotic installs
    QtWebEngineCore = QtWebEngineWidgets = None


def _assets_complete():
    """资源门禁的文件检查：help_assets 里门禁清单文件逐一存在。"""
    return all((ASSETS / name).is_file() for name in ASSET_FILES)


def _webengine_available():
    """QtWebEngine is used only on interactive platforms with local scripts."""
    if QtWebEngineWidgets is None or QtWebEngineCore is None:
        return False
    app = W.QApplication.instance()
    if app is not None and app.platformName() == 'offscreen':
        return False
    return _assets_complete()


def _chapter_html(markdown):
    payload = json.dumps(markdown).replace('</', '<\\/')
    return PAGE_TEMPLATE.replace('__PAYLOAD__', payload)


class TextHelpBrowser(W.QTextBrowser):
    """Fallback renderer: Mermaid fences display as plain code blocks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.document().setDocumentMargin(12)
        self.document().setDefaultStyleSheet(
            'h1,h2,h3 {color:#2149b8;} p,li {line-height:150%;} '
            'pre {background:#edf2f5;white-space:pre-wrap;} '
            'th,td {padding:6px;}')

    def show_markdown(self, text):
        self.setMarkdown(text)
        cursor = QtGui.QTextCursor(self.document())
        cursor.select(QtGui.QTextCursor.Document)
        spacing = QtGui.QTextBlockFormat()
        spacing.setLineHeight(140, QtGui.QTextBlockFormat.ProportionalHeight.value)
        spacing.setBottomMargin(8)
        cursor.mergeBlockFormat(spacing)
        self.verticalScrollBar().setValue(0)

    def show_message(self, text):
        self.setPlainText(text)


if QtWebEngineWidgets is not None:
    class HelpWebPage(QtWebEngineCore.QWebEnginePage):
        """External links open in the desktop browser; other navigation stays local."""

        def acceptNavigationRequest(self, url, kind, is_main_frame):
            if url.scheme() in ('http', 'https'):
                QtGui.QDesktopServices.openUrl(url)
                return False
            if (kind == QtWebEngineCore.QWebEnginePage.NavigationType.NavigationTypeLinkClicked
                    and url.toLocalFile().lower().endswith('.md')):
                return False  # 与旧版一致：跨文档 .md 链接在离线帮助中不跳转
            return True

        def createWindow(self, kind):
            return None

    class WebHelpBrowser(QtWebEngineWidgets.QWebEngineView):
        """Offline HTML renderer driven by help_assets (marked + mermaid + hljs)."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setPage(HelpWebPage(self))
            self._base = QtCore.QUrl.fromLocalFile(
                str(ASSETS).replace('\\', '/') + '/')

        def show_markdown(self, text):
            self.setHtml(_chapter_html(text), self._base)

        def show_message(self, text):
            body = '<body style="font-family:\'Microsoft YaHei UI\',sans-serif;">%s</body>'
            self.setHtml(body % html_lib.escape(text), self._base)
else:  # pragma: no cover - keeps GuidePage usable when WebEngine is missing
    WebHelpBrowser = None


class GuidePage(W.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        source = self.path.read_text(encoding='utf-8')
        chunks = re.split(r'^## ', source, flags=re.MULTILINE)
        self.chapters = [('开始阅读', chunks[0])]
        for chunk in chunks[1:]:
            title = chunk.split('\n', 1)[0].strip()
            self.chapters.append((title, '## ' + chunk))
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(16,16,16,16)
        layout.setSpacing(12)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText('搜索教程内容，例如：导出、训练、标签')
        layout.addWidget(self.search)
        split = W.QSplitter()
        self.contents = W.QListWidget()
        self.contents.setMinimumWidth(190)
        self.contents.setWordWrap(True)
        self.browser = (WebHelpBrowser() if _webengine_available()
                        else TextHelpBrowser())
        if isinstance(self.browser, TextHelpBrowser):
            self.browser.anchorClicked.connect(self.open_link)
        split.addWidget(self.contents)
        split.addWidget(self.browser)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 700])
        layout.addWidget(split, 1)
        self.contents.currentItemChanged.connect(self.show_chapter)
        self.search.textChanged.connect(self.filter_chapters)
        self.filter_chapters('')

    def filter_chapters(self, text):
        self.contents.clear()
        for title, body in self.chapters:
            if text.casefold() in (title + body).casefold():
                item = W.QListWidgetItem(title)
                item.setData(QtCore.Qt.UserRole, body)
                self.contents.addItem(item)
        if self.contents.count():
            self.contents.setCurrentRow(0)
        else:
            self.browser.show_message('没有找到相关章节。请尝试“导入”“采集”“模型”或清空搜索。')

    def show_chapter(self, item, previous=None):
        if item:
            self.browser.show_markdown(item.data(QtCore.Qt.UserRole))
            if isinstance(self.browser, TextHelpBrowser):
                self.browser.verticalScrollBar().setValue(0)

    def open_link(self, url):
        if url.scheme() in ('http', 'https'):
            QtGui.QDesktopServices.openUrl(url)
        elif url.fragment() and not url.path():
            self.browser.scrollToAnchor(url.fragment())


class HelpDialog(W.QDialog):
    def __init__(self, parent=None, docs_root=None):
        super().__init__(parent)
        self.setWindowTitle('EMG Lab 帮助与技术文档')
        self.resize(1000, 740)
        self.setMinimumSize(720, 500)
        root = Path(docs_root) if docs_root else ROOT / 'docs'
        layout = W.QVBoxLayout(self)
        self.tabs = W.QTabWidget()
        self.tabs.addTab(GuidePage(root / 'USER_GUIDE.md'), '操作教程')
        self.tabs.addTab(GuidePage(root / 'TECHNICAL_GUIDE.md'), '开发技术文档')
        self.tabs.addTab(GuidePage(root / 'COURSE_GUIDE.md'), '课堂与离线开发')
        self.tabs.addTab(GuidePage(root / 'COMPETITION.md'), '金币任务与比赛规则')
        layout.addWidget(self.tabs)
        footer = W.QDialogButtonBox(W.QDialogButtonBox.Close)
        footer.button(W.QDialogButtonBox.Close).setText('关闭')
        footer.rejected.connect(self.close)
        layout.addWidget(footer)
