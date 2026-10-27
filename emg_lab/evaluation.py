"""Continuous replay evaluation using exactly the deployed ONNX inference path."""
from collections import defaultdict
import hashlib
import numpy as np
from .inference import InferencePipeline, StableCommand
from .storage import read_recording, CLASSES, CLASS_NAMES
from .tasks import task_from_metadata


def summarize(confusion, classes=CLASSES):
    counts = confusion.sum(axis=1)
    total = int(counts.sum())
    return dict(accuracy=float(confusion.trace()/total) if total else None,
                correct=int(confusion.trace()), total=total, confusion_matrix=confusion.tolist(),
                per_class=[dict(class_id=i, name=classes[i], support=int(counts[i]),
                                correct=int(confusion[i,i]),
                                recall=float(confusion[i,i]/counts[i]) if counts[i] else None)
                           for i in range(len(classes))])


def evaluate_recordings(folder, metadata, units, *, split):
    """Replay whole files, but score only eligible actions in the held-out units.

    Filtering and command persistence include preparation and intervening trials.
    The stream's window grid is not re-anchored at each label boundary. No test
    signal is used to fit normalization, choose epochs, or tune decision settings.
    """
    if not units:
        return None
    by_path = defaultdict(list)
    for unit in units:
        by_path[unit['path']].append(unit)
    classes = task_from_metadata(metadata).classes
    raw_cm = np.zeros((len(classes),len(classes)),dtype=np.int64)
    command_cm = np.zeros_like(raw_cm)
    segment_count = 0
    for path, selected in sorted(by_path.items()):
        profile, raw, labels = read_recording(path)
        digest = hashlib.sha256(raw.tobytes()).hexdigest()
        if any(u['sha256'] != digest or u['record_id'] != profile['record_id'] for u in selected):
            raise ValueError('评估数据与训练时不一致，请重新选择数据。')
        whole_file = any(u['unit']=='legacy_session' for u in selected)
        trials = {u['trial'] for u in selected}
        segments = sorted((r for r in labels if whole_file or r['trial'] in trials),key=lambda r:r['start_sample'])
        segment_count += len(segments)
        pipeline = InferencePipeline(folder,profile,metadata=metadata)
        skip = round(.2*profile['sampling_rate'])
        chunk = max(1,round(profile['sampling_rate']))
        index = 0
        for offset in range(0,len(raw),chunk):
            for result in pipeline.feed(raw[offset:offset+chunk]):
                end = result['sample_end']
                while index < len(segments) and end > segments[index]['end_sample']:
                    index += 1
                if index == len(segments):
                    break
                label = segments[index]
                if end-pipeline.window >= label['start_sample']+skip:
                    true = label['class_id']
                    raw_cm[true,result['raw_class']] += 1
                    command_cm[true,result['filtered_class']] += 1
            if index == len(segments):
                break
    if not command_cm.sum():
        raise ValueError('留出数据中没有可评估的完整动作窗口。')
    return dict(version=1, split=split, protocol='continuous_recording_replay',
                score_scope='active_windows_after_200ms',
                decision=StableCommand(**metadata.get('decision',{})).settings,
                recording_count=len(by_path), trial_count=len(units), segment_count=segment_count,
                scored_windows=int(command_cm.sum()), raw=summarize(raw_cm,classes), command=summarize(command_cm,classes))


def evaluation_text(meta):
    report = meta.get('online_evaluation')
    if report:
        name = '测试回放' if report['split']=='test' else '验证回放'
        suffix = '' if report['split']=='test' else '（尚未独立测试）'
        return f"{name}最终指令正确率：{report['command']['accuracy']:.1%}{suffix}"
    if meta.get('test_accuracy') is not None:
        return f"窗口分类正确率：{meta['test_accuracy']:.1%}（旧评估）"
    if meta.get('validation_accuracy') is not None:
        return '已做初步验证，尚未独立测试'
    return '尚未评估推理效果'


def evaluation_details(meta):
    names = task_from_metadata(meta).names
    lines = [evaluation_text(meta)]
    report = meta.get('online_evaluation')
    if report:
        lines.append(f"同批窗口分类正确率：{report['raw']['accuracy']:.1%}；已连续回放 {report['segment_count']} 个留出动作，计分 {report['scored_windows']} 个窗口。")
        classes = report['command']['per_class']
        values = [f"{names[r['class_id']]} {r['recall']:.1%}（{r['correct']}/{r['support']}）"
                  for r in classes if r['support']]
        lines.append('各动作最终输出：'+' · '.join(values))
        absent = [names[r['class_id']] for r in classes if r['support'] and not r['correct']]
        if absent:
            lines.append('本次回放未正确输出：'+'、'.join(absent)+'。请先检查这几类的采集与训练结果。')
        lines.append('回放成绩不等于新一次实时操作效果；窗口有重叠，不代表独立动作次数。')
    elif meta.get('test_accuracy') is not None or meta.get('validation_accuracy') is not None:
        lines.append('旧评估尚未评估最终指令；重新训练后可查看各动作的回放结果。')
    else:
        lines.append('本次没有留出数据；模型已训练成功，需要后续采集或实时操作检验效果。')
    return '\n'.join(lines)
