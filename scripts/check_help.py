"""Help-window acceptance: QtWebEngine renders docs chapters with Mermaid SVGs,
code language badges and highlight.js coloring.

Run on a desktop session (not offscreen): the technical guide's Mermaid
diagrams must draw, every tab must load, no diagram may report an error, and
each fenced code block must carry the right badge/highlight decision.
"""
import json
import re
import sys
import time
from PySide6 import QtWidgets as W

from emg_lab.help import HelpDialog, WebHelpBrowser, PAGE_TEMPLATE
from emg_lab.storage import ROOT

# 语言清单一律以页面脚本为准，从这里解析，不维护第二份手工副本。
# 徽标豁免 = PLAIN 家族 + mermaid（图表围栏整体替换，不标徽标）。
_TMPL_PLAIN = re.search(r"var PLAIN = \[([^\]]*)\];", PAGE_TEMPLATE)
_TMPL_HL = re.search(r"var HIGHLIGHT = \{([^}]*)\};", PAGE_TEMPLATE)
PLAIN_LANGS = ({w.strip().strip("'\"") for w in _TMPL_PLAIN.group(1).split(',')}
               | {'mermaid'})
HIGHLIGHT_LANGS = {w.split(':')[0].strip() for w in _TMPL_HL.group(1).split(',')
                   if ':' in w}


def _fence_expectations(body):
    """Per chapter: (mermaid diagrams, language badges, highlighted blocks)."""
    langs = [m.group(1) for m in re.finditer(r'^```(\S+)\s*$', body, flags=re.MULTILINE)]
    mermaids = sum(1 for lang in langs if lang.lower() == 'mermaid')
    badges = sum(1 for lang in langs if lang.lower() not in PLAIN_LANGS)
    highlights = sum(1 for lang in langs if lang.lower() in HIGHLIGHT_LANGS)
    return mermaids, badges, highlights


def main():
    app = W.QApplication.instance() or W.QApplication([])
    out = ROOT / 'local' / 'help-check.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, renderer='none', chapters=[], errors=[])
    try:
        dialog = HelpDialog()
        page = dialog.tabs.widget(1)  # 开发技术文档
        if WebHelpBrowser is None or not isinstance(page.browser, WebHelpBrowser):
            report.update(passed=None, renderer='text-fallback',
                          errors=['WebEngine 未启用（offscreen 或缺少 help_assets）'])
            print('SKIP：当前环境回退到纯文本帮助，未验证渲染。')
            out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
            return 0

        def until(predicate, seconds=25):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return
                time.sleep(.02)
            raise AssertionError('等待帮助页面渲染超时')

        def evaluate(expr):
            box = []
            page.browser.page().runJavaScript(expr, box.append)
            until(lambda: box)
            return box[0]

        report['renderer'] = 'webengine'
        for row in range(page.contents.count()):
            item = page.contents.item(row)
            body = item.data(0x0100)  # QtCore.Qt.UserRole
            diagrams, badges, highlights = _fence_expectations(body)
            if not (diagrams or badges or highlights):
                continue
            page.contents.setCurrentRow(row)
            until(lambda: evaluate("document.readyState") == 'complete')
            if diagrams:
                until(lambda: evaluate(
                    "document.querySelectorAll('pre.mermaid svg').length") == diagrams,
                    seconds=40)
            broken = evaluate("document.querySelectorAll('pre.mermaid.mermaid-error').length")
            got_badges = evaluate("document.querySelectorAll('pre[data-lang]').length")
            got_highlights = evaluate(
                "document.querySelectorAll('pre code.hljs[data-highlighted=yes]').length")
            report['chapters'].append(dict(title=item.text(), diagrams=diagrams,
                                           badges=got_badges, highlighted=got_highlights,
                                           errors=broken))
            if broken:
                report['errors'].append(f"{item.text()}：{broken} 张图渲染失败")
            if got_badges != badges:
                report['errors'].append(f"{item.text()}：徽标 {got_badges} 个，应为 {badges} 个")
            if got_highlights != highlights:
                report['errors'].append(
                    f"{item.text()}：高亮 {got_highlights} 块，应为 {highlights} 块")
            print(f"章节《{item.text()}》 mermaid={diagrams} 徽标={got_badges}/{badges} "
                  f"高亮={got_highlights}/{highlights} 失败={broken}", flush=True)

        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            app.processEvents()

        report['passed'] = bool(report['chapters']) and not report['errors']
        print('帮助窗口检查：', '通过' if report['passed'] else '未通过', flush=True)
        return 0 if report['passed'] else 1
    except Exception as exc:  # noqa: BLE001 - report every failure shape
        report['errors'].append(repr(exc))
        print('帮助窗口检查失败：', exc, flush=True)
        return 1
    finally:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
