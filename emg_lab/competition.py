"""Deterministic coin routes, fixed class commands and reviewable race records."""
from dataclasses import dataclass, asdict
from datetime import datetime
from html import escape
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import uuid

from .storage import ROOT, DATA_ROOT, read_json, write_json, safe_name
from .physics.commands import CommandSettings, velocity_limits

VERSION = 'coin_race_v2'
RADIUS = .45
AREA_LIMIT = 7.2
FIXED_VELOCITIES = tuple(CommandSettings().velocity(i) for i in range(7))
RULES_FILE = 'competition_rules.json'
BASELINE_FILE = 'competition_baseline.json'
APPROVALS_FILE = 'competition_approvals.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def fixed_velocity(class_id):
    if isinstance(class_id,bool) or not isinstance(class_id,int) or not 0<=class_id<len(FIXED_VELOCITIES):
        raise ValueError('比赛只接受 0–6 的整数类别编号。')
    return FIXED_VELOCITIES[class_id]


@dataclass(frozen=True)
class RaceConfig:
    seed: int = 20261025
    count: int = 6
    limit_s: float = 120.
    official: bool = False
    group: str = '未分组'
    control_mode: str = 'fixed_classification'
    speed_tier: str = 'basic'

    def __post_init__(self):
        if type(self.seed) is not int or not 0<=self.seed<=2147483647:
            raise ValueError('种子须为 0–2147483647 的整数。')
        if type(self.count) is not int or not 1<=self.count<=20:
            raise ValueError('每局金币数须为 1–20。')
        if not math.isfinite(self.limit_s) or not 20<=self.limit_s<=600:
            raise ValueError('每局限时须为 20–600 秒。')
        safe_name(self.group)
        if self.control_mode not in ('fixed_classification','continuous'):
            raise ValueError('控制接口须为固定分类或连续速度。两者使用同一榜单。')
        if self.speed_tier not in ('basic','advanced') or (self.control_mode=='fixed_classification' and self.speed_tier!='basic'):
            raise ValueError('固定分类只能使用基础速度档；进阶档仅供验收后的连续/混合控制。')


def load_rules(root=ROOT):
    rules=read_json(Path(root)/RULES_FILE)
    if rules.get('version')!=VERSION or rules.get('ranking')!='unified':
        raise ValueError('比赛规则版本或统一排名设置不匹配。')
    if rules.get('fixed_velocities') != [list(v) for v in FIXED_VELOCITIES]:
        raise ValueError('固定类别速度表被修改，请恢复教师版本。')
    if rules.get('velocity_limits') != {tier:velocity_limits(tier) for tier in ('basic','advanced')}:
        raise ValueError('连续接口范围与教师程序不一致。')
    if rules.get('advanced_access') != 'teacher_reviewed_model_hashes':
        raise ValueError('进阶速度档须由教师验收授权。')
    seeds=rules.get('official_seeds',[])
    if len(seeds)!=3 or len(set(seeds))!=3:
        raise ValueError('教师规则须指定 3 个不同种子。')
    for seed in seeds:
        RaceConfig(seed,rules['count'],rules['limit_s'])
    return rules


def load_approvals(root=ROOT):
    """Teacher-maintained, baseline-protected review register; never a student checkbox."""
    import re
    register=read_json(Path(root)/APPROVALS_FILE)
    if register.get('version')!=VERSION or not isinstance(register.get('entries'),list):
        raise ValueError('教师进阶验收表格式无效。')
    entries=[]
    seen=set()
    for entry in register['entries']:
        if not isinstance(entry,dict):
            raise ValueError('教师进阶验收项须为对象。')
        if entry.get('approved') is not True:
            continue
        hashes=entry.get('model_hashes',{})
        capabilities=entry.get('capabilities',[])
        if (not isinstance(hashes,dict) or set(hashes)!= {'model.onnx','metadata.json'}
                or not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in hashes.values())
                or not isinstance(capabilities,list) or not capabilities or not all(isinstance(v,str) for v in capabilities)
                or not set(capabilities)<= {'continuous_amplitude','mixed_axes'}
                or not all(isinstance(entry.get(k),str) and entry[k].strip() for k in ('group','approved_by','evidence'))):
            raise ValueError('已批准的进阶验收项缺少组别、模型哈希、能力、教师或验收证据。')
        key=(entry['group'],tuple(sorted(hashes.items())))
        if key in seen:raise ValueError('同一组同一模型有重复的进阶批准项。')
        seen.add(key);entries.append(entry)
    return entries


def check_speed_access(config,context,root=ROOT):
    """Practice may explore advanced limits; formal entry is bound to approved model hashes."""
    if config.speed_tier=='advanced' and config.official:
        matches=[entry for entry in load_approvals(root) if entry['group']==config.group
                 and entry['model_hashes']==context.get('model_hashes')]
        if not matches:
            raise ValueError('进阶速度档尚未通过教师验收，或组别/模型哈希不匹配。')
    return velocity_limits(config.speed_tier)


def make_route(config):
    """Precompute world coordinates; never consult participant position/camera."""
    rng=random.Random(config.seed)
    points=[]
    previous=(0.,0.)
    for index in range(config.count):
        for _ in range(10000):
            angle=(rng.choice((-1,1))*rng.uniform(.4,1.) if index==0 else rng.uniform(-math.pi,math.pi))
            distance=rng.uniform(2.2,3.2)
            point=(round(previous[0]+distance*math.cos(angle),6),round(previous[1]+distance*math.sin(angle),6))
            if max(abs(v) for v in point)>6.5:
                continue
            if any(math.dist(point,old)<1.0 for old in [(0.,0.),*points]):
                continue
            points.append(point)
            previous=point
            break
        else:
            raise ValueError('此配置无法生成路线，请更换种子。')
    return points


class Race:
    def __init__(self, config):
        self.config=config
        self.route=make_route(config)
        self.route_hash=digest(dict(version=VERSION,seed=config.seed,points=self.route))
        self.started=None
        self.sim_started=None
        self.elapsed=0.
        self.collected=[]
        self.reason=None
        self.slow_since=None
        self.last_wall=None

    @property
    def target(self):
        return self.route[len(self.collected)] if not self.reason and len(self.collected)<len(self.route) else None

    def start(self, wall, sim_time):
        if self.started is not None or self.reason:
            raise ValueError('每局只能开始一次。')
        self.started=self.last_wall=float(wall)
        self.sim_started=float(sim_time)

    def finish(self, reason, wall=None):
        if self.reason:
            return
        if wall is not None and self.started is not None:
            self.elapsed=max(self.elapsed,min(self.config.limit_s,wall-self.started))
        self.reason=reason

    def update(self, status, wall):
        if self.reason or self.started is None:
            return
        if not math.isfinite(wall) or wall<self.last_wall:
            self.finish('clock_error')
            return
        self.last_wall=wall
        self.elapsed=min(self.config.limit_s,wall-self.started)
        xy=status['position'][:2]
        if not all(math.isfinite(float(v)) for v in xy):
            self.finish('invalid_physics')
        elif status['fallen'] or status.get('tilt_deg',0)>60:
            self.finish('fallen')
        elif max(abs(float(v)) for v in xy)>AREA_LIMIT:
            self.finish('out_of_bounds')
        elif wall-self.started>=self.config.limit_s:
            self.finish('timeout')
        else:
            sim_elapsed=status['time']-self.sim_started
            lag=(wall-self.started)-sim_elapsed
            if lag>.75:
                self.slow_since=wall if self.slow_since is None else self.slow_since
                if wall-self.slow_since>2.:
                    self.finish('slow_machine')
            else:
                self.slow_since=None
            if not self.reason and math.dist(xy,self.target)<=RADIUS:
                self.collected.append(dict(index=len(self.collected)+1,seconds=round(self.elapsed,4),position=list(xy)))
                if len(self.collected)==self.config.count:
                    self.finish('completed')

    def snapshot(self):
        return dict(version=VERSION,config=asdict(self.config),route=self.route,route_hash=self.route_hash,
                    target=self.target,collected=self.collected.copy(),count=len(self.collected),
                    completion=len(self.collected)/self.config.count,elapsed=self.elapsed,
                    remaining=max(0,self.config.limit_s-self.elapsed),reason=self.reason,
                    scored_seconds=self.elapsed if self.reason=='completed' else self.config.limit_s,
                    infrastructure_valid=self.reason not in ('slow_machine','clock_error','invalid_physics','integrity_error','startup_error'))


def protected_files(root):
    root=Path(root)
    paths=[]
    for folder in ('emg_lab','assets','vendor','scripts'):
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and p.suffix.lower() not in ('.pyc','.pyo'))
    paths.extend(root/name for name in ('main.py','requirements.txt',RULES_FILE,APPROVALS_FILE))
    return {p.relative_to(root).as_posix():file_hash(p) for p in sorted(paths)}


def runtime_versions():
    return {name:importlib.metadata.version(name) for name in ('numpy','mujoco','onnxruntime','PySide6')}


def verify_baseline(root=ROOT, manifest=None):
    root=Path(root)
    manifest=Path(manifest) if manifest else root/BASELINE_FILE
    baseline=read_json(manifest)
    actual=protected_files(root)
    expected=baseline.get('files',{})
    changes=sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
    if baseline.get('version')!=VERSION or not expected:
        raise ValueError('比赛基准文件无效，请使用教师审核的完整程序。')
    if changes:
        raise ValueError('比赛程序或资产校验不通过：'+', '.join(changes[:5]))
    if runtime_versions()!=baseline.get('runtime'):
        raise ValueError('运行依赖版本与教师基准不一致。')
    load_rules(root)
    load_approvals(root)
    return file_hash(manifest)


def check_entry(config, source, profile, root=ROOT):
    if config.official:
        rules=load_rules(root)
        if config.seed not in rules['official_seeds'] or config.count!=rules['count'] or config.limit_s!=rules['limit_s']:
            raise ValueError('正式比赛必须使用教师规定的种子、金币数与限时。')
        if source!='live' or not profile or profile.get('device') not in ('Cometa','Delsys'):
            raise ValueError('正式比赛只接受真实设备的实时肌电；回放和模拟信号可用于练习。')
        return verify_baseline(root)
    return None


REASONS={'completed':'全部收集完成','timeout':'时间结束','fallen':'机器人跌倒','out_of_bounds':'越出训练区',
         'aborted':'提前结束','signal_lost':'输入信号中断','slow_machine':'仿真速度不足，成绩需重测',
         'integrity_error':'程序校验失败','invalid_physics':'物理状态异常','clock_error':'计时异常',
         'startup_error':'启动失败','replay_finished':'回放结束'}


class RaceLog:
    def __init__(self, config, context, root=DATA_ROOT):
        self.context=dict(context)
        self.config=config
        self.folder=Path(root)/safe_name(config.group)/'competitions'/f'{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}'
        self.folder.mkdir(parents=True,exist_ok=False)
        self.handle=(self.folder/'commands.jsonl').open('w',encoding='utf-8')
        self.count=0
        self.finished=False
        write_json(self.folder/'result.json',dict(version=VERSION,state='incomplete',config=asdict(config),context=self.context))

    def record(self, race, status, predicted, expired, submitted=None):
        self.handle.write(json.dumps(dict(wall_seconds=race.elapsed,simulation_seconds=status['time'],
             class_id=int(predicted) if predicted is not None else None,submitted=submitted,
             expired=bool(expired),requested=status['requested'],applied=status['applied'],
             effective=status['effective'],position=status['position'],yaw=status['yaw'],height=status['height'],
             tilt_deg=status['tilt_deg'],fallen=status['fallen'],collected=len(race.collected)),allow_nan=False)+'\n')
        self.count+=1
        if self.count%50==0:
            self.handle.flush()

    def finish(self, race, root=ROOT):
        if self.finished:
            return self.folder/'report.html'
        self.finished=True
        self.handle.close()
        integrity=None
        try:
            if self.config.official:
                check_speed_access(self.config,self.context,root)
                integrity=verify_baseline(root)
                if integrity!=self.context['baseline_sha256']:
                    raise ValueError('基准文件与开赛前不同。')
            model=Path(self.context['model'])
            if self.context['model_hashes']!={name:file_hash(model/name) for name in ('model.onnx','metadata.json')}:
                raise ValueError('模型文件在比赛期间发生变化。')
        except Exception as error:
            race.reason='integrity_error'
            self.context['integrity_error']=str(error)
        report=dict(race.snapshot(),context=self.context,state='finalized',control_mode=self.config.control_mode,
                    command_rows=self.count,commands_sha256=file_hash(self.folder/'commands.jsonl'),baseline_after=integrity)
        report['official_eligible']=bool(self.config.official and report['infrastructure_valid'])
        write_json(self.folder/'result.json',report)
        (self.folder/'report.html').write_text(report_html(report),encoding='utf-8')
        return self.folder/'report.html'


def report_html(report):
    esc=lambda v:escape(str(v))
    cfg=report['config']
    rows=''.join(f"<tr><td>{i+1}</td><td>{point[0]:.3f}, {point[1]:.3f}</td><td>{report['collected'][i]['seconds'] if i<len(report['collected']) else '未收集'}</td></tr>" for i,point in enumerate(report['route']))
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>机器人金币任务报告</title>
    <style>body{{max-width:900px;margin:40px auto;padding:0 24px;font:16px/1.7 "Microsoft YaHei",sans-serif;color:#24344a}}h1{{font-size:28px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border:1px solid #d7e0ea}}th{{background:#edf2fa}}code{{overflow-wrap:anywhere}}</style>
    <h1>机器人金币任务报告</h1><p>{'正式比赛 · 待教师复核' if report['official_eligible'] else '练习记录 / 不计正式成绩'} · {esc(cfg['group'])}</p>
    <p><b>{report['count']} / {cfg['count']} 枚 · 完成率 {report['completion']:.0%}</b><br>
    {esc(REASONS.get(report['reason'],report['reason']))} · 实际用时 {report['elapsed']:.2f} 秒 · 计分用时 {report['scored_seconds']:.2f} 秒</p>
    <p>种子 {cfg['seed']} · 限时 {cfg['limit_s']:g} 秒 · 控制方式：{esc(report['control_mode'])} · 统一榜单<br>速度档位：{esc(cfg['speed_tier'])}。未全部完成时记整局限时；先比收集总数，再比总计分用时。进阶奖励仅体现在可用速度范围，时间不打折。</p>
    <table><tr><th>金币</th><th>世界坐标（米）</th><th>收集时刻（秒）</th></tr>{rows}</table>
    <p>路线 SHA-256：<code>{report['route_hash']}</code><br>模型：{esc(report['context'].get('model_id',''))}<br>
    逐步命令记录：commands.jsonl（{report['command_rows']} 行）；完整配置与模型校验值：result.json。</p>
    <p>本机校验用于发现改动；正式成绩需由教师在受控电脑运行并留存记录，不能仅凭学生提交的报告认定。</p></html>'''
