"""One leaderboard for all declared decoder types; explicit attempts only."""
import argparse
from collections import defaultdict
import csv
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from emg_lab.storage import read_json
from emg_lab.competition import check_speed_access, Race, RaceConfig, load_rules, file_hash, fixed_velocity, RADIUS
from emg_lab.physics.commands import clamp_velocity


def validate_result(path,rules,baseline_sha):
    report=read_json(path)
    cfg=report['config']
    config=RaceConfig(**cfg)
    if not report.get('official_eligible') or report.get('state')!='finalized' or not cfg['official']:
        raise ValueError(f'{path}: 不是有效的正式记录。')
    if (cfg['seed'] not in rules['official_seeds'] or cfg['count']!=rules['count'] or cfg['limit_s']!=rules['limit_s']):
        raise ValueError(f'{path}: 规则不同。')
    if report['context']['baseline_sha256']!=baseline_sha or report['baseline_after']!=baseline_sha:
        raise ValueError(f'{path}: 与指定教师基准不一致。')
    check_speed_access(config,report['context'])
    race=Race(config)
    if report['route_hash']!=race.route_hash or report['route']!=[list(v) for v in race.route]:
        raise ValueError(f'{path}: 路线不匹配。')
    trace=path.with_name('commands.jsonl')
    if file_hash(trace)!=report['commands_sha256']:
        raise ValueError(f'{path}: 指令记录已改变。')
    import json
    count=0
    last=-1.
    collected=[]
    for line in trace.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        count+=1
        now=row['wall_seconds']
        if not math.isfinite(now) or now<last or now>config.limit_s:
            raise ValueError(f'{path}: 时间记录无效。')
        last=now
        if config.control_mode=='fixed_classification':
            expected=fixed_velocity(0 if row['expired'] or row['fallen'] else row['class_id'])
        else:
            expected=clamp_velocity((0,0,0) if row['expired'] or row['fallen'] else row['submitted'],config.speed_tier)
        if any(abs(a-b)>1e-9 for a,b in zip(row['requested'],expected)) or len(row['requested'])!=3:
            raise ValueError(f'{path}: 指令未遵守规定速度表或限幅。')
        if row['collected']!=len(collected):
            if (row['collected']!=len(collected)+1 or len(collected)>=config.count or now>=config.limit_s
                or math.dist(row['position'][:2],race.route[len(collected)])>RADIUS):
                raise ValueError(f'{path}: 收集记录无效。')
            collected.append(now)
    if count!=report['command_rows'] or len(collected)!=report['count'] or len(report['collected'])!=len(collected):
        raise ValueError(f'{path}: 记录数量不一致。')
    for timestamp,event in zip(collected,report['collected']):
        if abs(timestamp-event['seconds'])>.0001:
            raise ValueError(f'{path}: 收集时刻不一致。')
    completed=report['reason']=='completed'
    if completed != (report['count']==config.count):
        raise ValueError(f'{path}: 完成状态不一致。')
    if completed and abs(report['elapsed']-last)>1e-6:
        raise ValueError(f'{path}: 完成用时与指令记录不同。')
    expected_time=report['elapsed'] if completed else config.limit_s
    if not 0<=report['elapsed']<=config.limit_s or abs(report['scored_seconds']-expected_time)>1e-6:
        raise ValueError(f'{path}: 计分用时无效。')
    return report


def rank(paths,rules,baseline_sha):
    from emg_lab.competition import verify_baseline
    if verify_baseline()!=baseline_sha:
        raise ValueError('当前教师程序与指定可信基准不同，不能据此汇总或批准进阶速度。')
    groups=defaultdict(list)
    if len({Path(p).resolve() for p in paths})!=len(paths):
        raise ValueError('同一份记录不能重复提交。')
    for path in paths:
        report=validate_result(Path(path),rules,baseline_sha)
        groups[report['config']['group']].append(report)
    results=[]
    for group,rows in groups.items():
        if sorted(r['config']['seed'] for r in rows)!=sorted(rules['official_seeds']):
            raise ValueError(f'{group}: 必须恰好提交每个规定种子的一局成绩，不能自动取最好的一局。')
        if len({tuple(sorted(r['context']['model_hashes'].items())) for r in rows})!=1:
            raise ValueError(f'{group}: 三局之间模型发生了变化。')
        if len({r['config']['speed_tier'] for r in rows})!=1:
            raise ValueError(f'{group}: 三局之间速度档位发生了变化。')
        collected=sum(r['count'] for r in rows)
        results.append(dict(group=group,collected=collected,total=3*rules['count'],
            completion=collected/(3*rules['count']),scored_seconds=round(sum(r['scored_seconds'] for r in rows),4),
            speed_tier=rows[0]['config']['speed_tier'],control_modes='/'.join(sorted({r['control_mode'] for r in rows}))))
    results.sort(key=lambda r:(-r['collected'],r['scored_seconds']))
    previous=None
    for index,result in enumerate(results):
        score=(result['collected'],result['scored_seconds'])
        result['rank']=index+1 if score!=previous else results[index-1]['rank']
        previous=score
    return results


def main():
    parser=argparse.ArgumentParser(description='统一榜单；明确指定每组的 3 份正式 result.json。')
    parser.add_argument('--baseline-sha256',required=True,help='教师独立保管的可信基准 SHA256')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('results',nargs='+',type=Path)
    args=parser.parse_args()
    rows=rank(args.results,load_rules(),args.baseline_sha256)
    if not rows: parser.error('没有成绩。')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['rank','group','collected','total','completion','scored_seconds','speed_tier','control_modes'])
        writer.writeheader(); writer.writerows(rows)
    for row in rows: print(row)


if __name__=='__main__': main()
