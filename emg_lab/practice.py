"""Sample-clock classroom assessment; targets NEVER enter the decoder/output."""
from html import escape
import numpy as np
from .evaluation import summarize


class BasicAssessment:
    def __init__(self, task, rate, window, *, labels=None, source='live'):
        self.task,self.rate,self.window = task,float(rate),int(window)
        self.source = source
        self.seed = int(np.random.SeedSequence().entropy) if labels is None else None
        if labels is None:
            order = np.concatenate([np.random.default_rng(self.seed+i).permutation(len(task.classes)) for i in range(2)])
            self.segments = [dict(class_id=int(c),start_sample=round((i*6+3)*rate),
                                 end_sample=round((i*6+6)*rate),trial=i//len(task.classes)+1)
                             for i,c in enumerate(order)]
        else:
            self.segments = sorted([dict(r) for r in labels],key=lambda r:r['start_sample'])
        self.end = max((r['end_sample'] for r in self.segments),default=0)
        self.raw_cm = np.zeros((len(task.classes),len(task.classes)),dtype=np.int64)
        self.cm = np.zeros_like(self.raw_cm)
        self.seen = 0
        self.last_prediction = 0
        self.first_correct = {}
        self.index = 0
        self.behavior=[dict(windows=0,correct=0,switches=0,wrong_motion_events=0,longest_correct_seconds=0.) for _ in self.segments]
        self.previous={}
        self.correct_start={}

    def feed(self, results, samples):
        self.seen += samples
        for result in results:
            end = result['sample_end']
            self.last_prediction=result['filtered_class']
            while self.index<len(self.segments) and end>self.segments[self.index]['end_sample']:
                self.index+=1
            if self.index == len(self.segments):
                continue
            segment=self.segments[self.index]
            # Same full-window eligibility as offline training evaluation.
            if end-self.window < segment['start_sample']+round(.2*self.rate):
                continue
            true = segment['class_id']
            self.raw_cm[true,result['raw_class']] += 1
            self.cm[true,result['filtered_class']] += 1
            predicted=result['filtered_class']
            metrics=self.behavior[self.index]
            metrics['windows']+=1
            previous=self.previous.get(self.index)
            if previous is not None and previous!=predicted:metrics['switches']+=1
            if predicted not in (0,true) and previous!=predicted:metrics['wrong_motion_events']+=1
            self.previous[self.index]=predicted
            if result['filtered_class']==true:
                metrics['correct']+=1
                beginning=self.correct_start.setdefault(self.index,end)
                metrics['longest_correct_seconds']=max(metrics['longest_correct_seconds'],(end-beginning)/self.rate)
                self.first_correct.setdefault(self.index,(end-segment['start_sample'])/self.rate)
            else:
                self.correct_start.pop(self.index,None)

    def status(self):
        target=None
        phase='完成'
        remaining=0.
        for seg in self.segments:
            if self.seen<seg['end_sample']:
                target=seg['class_id']
                phase='准备' if self.seen<seg['start_sample'] else '动作'
                remaining=(seg['start_sample']-self.seen if phase=='准备' else seg['end_sample']-self.seen)/self.rate
                break
        score=summarize(self.cm,self.task.classes)
        return dict(done=self.seen>=self.end,phase=phase,target=target,remaining=remaining,
                    correct=score['correct'],total=score['total'],accuracy=score['accuracy'],
                    prediction=self.last_prediction)

    def report(self, complete=None):
        stop=[m for s,m in zip(self.segments,self.behavior) if s['class_id']==0]
        stop_windows=sum(m['windows'] for m in stop)
        false_windows=sum(m['windows']-m['correct'] for m in stop)
        return dict(version=2,mode='basic_assessment',source=self.source,
                    complete=self.seen>=self.end if complete is None else bool(complete),
                    classes=list(self.task.classes),names=list(self.task.names),
                    task_type=self.task.task_type,order_seed=self.seed,
                    scored_scope='full_windows_after_target_start_plus_200ms',
                    raw=summarize(self.raw_cm,self.task.classes),
                    command=summarize(self.cm,self.task.classes),
                    segments=[dict(s,first_correct_seconds=self.first_correct.get(i),**self.behavior[i]) for i,s in enumerate(self.segments)],
                    stop=dict(windows=stop_windows,false_motion_windows=false_windows,
                              false_motion_fraction=false_windows/stop_windows if stop_windows else None,
                              false_motion_events=sum(m['wrong_motion_events'] for m in stop)),
                    note='提示时序标签；首次正确输出时间包含人的反应与处理链路。重叠窗口不是独立动作次数。')


def report_html(report):
    score=report['command']
    names=report['names']
    esc=lambda s:escape(str(s))
    accuracy='尚无有效窗口' if score['accuracy'] is None else f"{score['accuracy']:.1%}"
    rows=''.join(f"<tr><td>{esc(names[r['class_id']])}</td><td>{r['support']}</td><td>{r['correct']}</td><td>{'—' if r['recall'] is None else format(r['recall'],'.1%')}</td></tr>" for r in score['per_class'])
    matrix=''.join('<tr><th>'+esc(names[i])+'</th>'+''.join(f'<td>{n}</td>' for n in row)+'</tr>' for i,row in enumerate(score['confusion_matrix']))
    behavior=''
    for i,s in enumerate(report['segments']):
        first='未正确输出' if s.get('first_correct_seconds') is None else f"{s['first_correct_seconds']:.2f} s"
        fraction=f"{s['correct']/s['windows']:.0%}" if s.get('windows') else '无有效窗口'
        behavior+=f"<tr><td>{i+1}</td><td>{esc(names[s['class_id']])}</td><td>{first}</td><td>{fraction}</td><td>{s.get('switches',0)}</td><td>{s.get('longest_correct_seconds',0):.2f} s</td></tr>"
    stop=report.get('stop',{})
    false_rate='无有效停止窗口' if stop.get('false_motion_fraction') is None else f"{stop['false_motion_fraction']:.1%}"
    notes=report.get('collection_notes',{})
    operator=notes.get('operator','') if isinstance(notes,dict) else ''
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>基础评估报告</title>
    <style>body{{max-width:1000px;margin:40px auto;font:16px/1.6 "Microsoft YaHei",sans-serif;color:#203047;padding:0 24px}}
    table{{border-collapse:collapse;width:100%;margin:16px 0 28px}}td,th{{padding:9px;border:1px solid #d4dce5;text-align:center}}th{{background:#eef3fa}}h1{{font-size:26px}}</style>
    <h1>基础评估报告</h1><p>{'已完成' if report['complete'] else '提前结束'} · 最终指令正确率：{accuracy} · 有效窗口：{score['total']}</p>
    <p>{esc(report.get('interpretation',''))}</p><p>{esc(report.get('note',''))}</p>
    <h2>放松时能否停止</h2><p>停止动作段中的误动作窗口比例：<b>{false_rate}</b>；错误运动指令出现 <b>{stop.get('false_motion_events',0)}</b> 次。</p>
    <p>这里只统计标签为“停止”的有效窗口。同一种错误运动连续输出算一次，切换到另一种错误运动另算一次。</p>
    <h2>动作响应与稳定性</h2><table><tr><th>段</th><th>提示动作</th><th>首次正确</th><th>正确占比</th><th>段内切换</th><th>最长连续正确跨度</th></tr>{behavior}</table>
    <p>首次正确从提示动作开始计时，包含人的反应、窗口与判定延迟。段内切换统计相邻有效预测的指令变化；连续正确跨度从首次到末次正确输出计时。以上是解码指令表现，不是机器人/机械手的到位时间或实际保持精度。</p>
    <h2>各类别表现</h2><table><tr><th>动作</th><th>窗口数</th><th>正确数</th><th>召回率</th></tr>{rows}</table>
    <h2>混淆矩阵</h2><p>行是真实提示标签，列是模型最终指令。</p><table><tr><th>标签 / 预测</th>{''.join('<th>'+esc(n)+'</th>' for n in names)}</tr>{matrix}</table>
    <p>时间：{esc(report.get('created_at',''))}<br>操作者代号：{esc(operator or '未填写')}<br>模型：{esc(report.get('model_id',''))}<br>数据：{esc(report.get('record_id') or '实时采集')}</p></html>"""
