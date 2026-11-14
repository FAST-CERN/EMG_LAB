"""Find and export existing reports; does not recompute or rank results."""

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from emg_lab.backend.data.storage import read_json


def find_reports(root, group=""):
    root = Path(root)
    rows = []
    for path in [*root.glob("*/evaluations/*.json"), *root.glob("*/competitions/*/result.json")]:
        try:
            report = read_json(path)
            coin = path.name == "result.json"
            html = path.with_name("report.html") if coin else path.with_suffix(".html")
            name = report.get("config", {}).get("group", "") if coin else report.get("group", "")
            if not html.is_file() or (group and group != name):
                continue
            context = report.get("context", {}) if coin else report
            accuracy = report.get("command", {}).get("accuracy")
            result = (
                f"{report.get('count', 0)}/{report.get('config', {}).get('count', 0)} 枚 · {report.get('elapsed', 0):.1f} s"
                if coin
                else f"{accuracy:.1%}"
                if accuracy is not None
                else "无有效窗口"
            )
            if not coin and not report.get("complete"):
                result += " · 提前结束"
            rows.append(
                dict(
                    path=path,
                    html=html,
                    group=name,
                    model=context.get("model_id", ""),
                    kind="金币任务" if coin else "基础评估",
                    result=result,
                    date=datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    stamp=path.stat().st_mtime,
                )
            )
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(rows, key=lambda r: r["stamp"], reverse=True)


def export_reports(rows, destination):
    if not rows:
        raise ValueError("请先选中要导出的报告。")
    output = Path(destination) / f"评估记录_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    output.mkdir(exist_ok=False)
    for i, row in enumerate(rows, 1):
        folder = output / f"{i:02d}"
        folder.mkdir()
        for path in (row["path"], row["html"]):
            shutil.copy2(path, folder / path.name)
        trace = row["path"].with_name("commands.jsonl")
        if row["kind"] == "金币任务" and trace.is_file():
            shutil.copy2(trace, folder / trace.name)
    (output / "阅读说明.txt").write_text(
        "每个编号文件夹含一份 HTML 报告和原始 JSON。金币任务另附现有指令记录。\n这些是已保存的结果，未重新计分。不同数据、佩戴、速度档位的结果不能直接说明算法优劣。\n",
        encoding="utf-8",
    )
    return output
