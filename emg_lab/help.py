"""Searchable offline help, using the same Markdown files as the developer docs."""
from pathlib import Path
import re
from PySide6 import QtCore, QtGui, QtWidgets as W

from .storage import ROOT


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
        self.browser = W.QTextBrowser()
        self.browser.document().setDocumentMargin(12)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDefaultStyleSheet(
            'h1,h2,h3 {color:#2149b8;} p,li {line-height:150%;} '
            'pre {background:#edf2f5;white-space:pre-wrap;} '
            'th,td {padding:6px;}')
        split.addWidget(self.contents)
        split.addWidget(self.browser)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 700])
        layout.addWidget(split, 1)
        self.contents.currentItemChanged.connect(self.show_chapter)
        self.search.textChanged.connect(self.filter_chapters)
        self.browser.anchorClicked.connect(self.open_link)
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
            self.browser.setPlainText('没有找到相关章节。请尝试“导入”“采集”“模型”或清空搜索。')

    def show_chapter(self, item, previous=None):
        if item:
            self.browser.setMarkdown(item.data(QtCore.Qt.UserRole))
            cursor = QtGui.QTextCursor(self.browser.document())
            cursor.select(QtGui.QTextCursor.Document)
            spacing = QtGui.QTextBlockFormat()
            spacing.setLineHeight(140, QtGui.QTextBlockFormat.ProportionalHeight.value)
            spacing.setBottomMargin(8)
            cursor.mergeBlockFormat(spacing)
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
