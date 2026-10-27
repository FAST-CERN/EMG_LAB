"""Help-window acceptance: QtWebEngine renders docs chapters with Mermaid SVGs.

Run on a desktop session (not offscreen): the technical guide's Mermaid
diagrams must draw, every tab must load, and no diagram may report an error.
"""
import json
import re
import sys
import time
from PySide6 import QtWidgets as W

from emg_lab.help import HelpDialog, WebHelpBrowser
from emg_lab.storage import ROOT


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
            print('SKIP：当前环境回退到纯文本帮助，未验证 Mermaid 渲染。')
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
            expected = len(re.findall(r'^```mermaid$', body, flags=re.MULTILINE))
            if not expected:
                continue
            page.contents.setCurrentRow(row)
            until(lambda: evaluate("document.readyState") == 'complete')
            until(lambda: evaluate("document.querySelectorAll('pre.mermaid svg').length") == expected,
                  seconds=40)
            broken = evaluate("document.querySelectorAll('pre.mermaid.mermaid-error').length")
            report['chapters'].append(dict(title=item.text(), diagrams=expected, errors=broken))
            if broken:
                report['errors'].append(f"{item.text()}：{broken} 张图渲染失败")
            print(f"章节《{item.text()}》 mermaid={expected} 失败={broken}", flush=True)

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
