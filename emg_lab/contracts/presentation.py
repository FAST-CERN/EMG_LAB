from .tasks import task_from_metadata


def evaluation_text(meta):
    report = meta.get("online_evaluation")
    if report:
        name = "测试回放" if report["split"] == "test" else "验证回放"
        suffix = "" if report["split"] == "test" else "（尚未独立测试）"
        return f"{name}最终指令正确率：{report['command']['accuracy']:.1%}{suffix}"
    if meta.get("test_accuracy") is not None:
        return f"窗口分类正确率：{meta['test_accuracy']:.1%}（旧评估）"
    if meta.get("validation_accuracy") is not None:
        return "已做初步验证，尚未独立测试"
    return "尚未评估推理效果"


def evaluation_details(meta):
    names = task_from_metadata(meta).names
    lines = [evaluation_text(meta)]
    report = meta.get("online_evaluation")
    if report:
        lines.append(
            f"同批窗口分类正确率：{report['raw']['accuracy']:.1%}；已连续回放 {report['segment_count']} 个留出动作，计分 {report['scored_windows']} 个窗口。"
        )
        classes = report["command"]["per_class"]
        values = [
            f"{names[r['class_id']]} {r['recall']:.1%}（{r['correct']}/{r['support']}）"
            for r in classes
            if r["support"]
        ]
        lines.append("各动作最终输出：" + " · ".join(values))
        absent = [names[r["class_id"]] for r in classes if r["support"] and not r["correct"]]
        if absent:
            lines.append(
                "本次回放未正确输出：" + "、".join(absent) + "。请先检查这几类的采集与训练结果。"
            )
        lines.append("回放成绩不等于新一次实时操作效果；窗口有重叠，不代表独立动作次数。")
    elif meta.get("test_accuracy") is not None or meta.get("validation_accuracy") is not None:
        lines.append("旧评估尚未评估最终指令；重新训练后可查看各动作的回放结果。")
    else:
        lines.append("本次没有留出数据；模型已训练成功，需要后续采集或实时操作检验效果。")
    return "\n".join(lines)
