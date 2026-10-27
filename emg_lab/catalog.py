"""Local data/model catalogue and portable classroom bundles, independent of Qt."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from importlib import metadata as packages
import json
from pathlib import Path
import uuid

from . import transfer
from .storage import ROOT, list_models, list_recordings, read_json, usable_record
from .tasks import task_from_metadata


@dataclass(frozen=True)
class Entry:
    kind: str
    path: Path
    meta: dict

    @property
    def task(self):
        return task_from_metadata(self.meta)

    @property
    def identity(self):
        return self.meta.get('record_id' if self.kind == 'recording' else 'model_id', '')

    @property
    def day(self):
        try:
            return date.fromisoformat(self.meta.get('created_at', '')[:10])
        except ValueError:
            return None


def catalogue(root):
    entries = []
    for kind, read in (('recording', list_recordings), ('model', list_models)):
        for path, meta in read(root):
            try:
                task_from_metadata(meta)
                entries.append(Entry(kind, Path(path), meta))
            except ValueError:
                continue
    return sorted(entries, key=lambda e:e.meta.get('created_at', ''), reverse=True)


def filter_entries(entries, *, query='', kind='', target='', group='', device='', start=None, end=None):
    query = query.strip().casefold()
    return [entry for entry in entries
            if (not kind or entry.kind == kind)
            and (not target or entry.task.key == target)
            and (not group or entry.meta.get('group') == group)
            and (not device or entry.meta.get('device') == device)
            and (start is None or entry.day is not None and entry.day >= start)
            and (end is None or entry.day is not None and entry.day <= end)
            and (not query or query in ' '.join(str(entry.meta.get(k, ''))
                 for k in ('name','group','record_id','model_id')).casefold())]


def inspect_file(path):
    path = Path(path)
    if path.suffix.lower() == '.emg' or path.name.lower() == 'emg.bin':
        kind, names, limit = 'recording', transfer.RECORD_MEMBERS, transfer.MAX_RECORD_BYTES
        source = transfer._record_source(path)
    elif path.suffix.lower() == '.emgmodel' or path.name.lower() == 'model.onnx':
        kind, names, limit = 'model', transfer.MODEL_MEMBERS, transfer.MAX_MODEL_BYTES
        source = path.parent if path.suffix.lower() == '.onnx' else path
    else:
        raise ValueError('请选择 .emg 数据、.emgmodel 模型包或旧版 emg.bin / model.onnx。')
    payload = transfer._read_members(source, names, limit)
    meta = json.loads(payload[names[-1]].decode('utf-8'))
    return Entry(kind, path, meta)


def import_file(path, root):
    entry = inspect_file(path)
    importer = transfer.import_recording if entry.kind == 'recording' else transfer.import_model
    return importer(path, root, entry.task)


def export_entry(entry, destination):
    exporter = transfer.export_recording if entry.kind == 'recording' else transfer.export_model
    return exporter(entry.path, destination, entry.task)


def training_ids(entry):
    if entry.kind != 'model':
        return set()
    return {unit['record_id'] for units in entry.meta.get('split', {}).values()
            for unit in units if isinstance(unit, dict) and unit.get('record_id')}


def with_training_data(selected, entries):
    result = {str(entry.path):entry for entry in selected}
    requested = set().union(*(training_ids(e) for e in selected)) if selected else set()
    for entry in entries:
        if entry.kind == 'recording' and entry.identity in requested:
            result[str(entry.path)] = entry
    found = {entry.identity for entry in result.values() if entry.kind == 'recording'}
    return list(result.values()), sorted(requested-found)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(project=ROOT):
    project = Path(project)
    paths = sorted([*project.glob('emg_lab/**/*.py'), *project.glob('requirements*.txt'),
                    *project.glob('constraints.txt'), *project.glob('assets/classroom/*.xml')])
    files = {path.relative_to(project).as_posix():file_hash(path) for path in paths}
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    versions = {}
    for name in ('numpy','scipy','torch','onnxruntime','PySide6','mujoco'):
        try:
            versions[name] = packages.version(name)
        except packages.PackageNotFoundError:
            versions[name] = None
    return dict(fingerprint=fingerprint, files=files, installed_packages=versions)


def export_bundle(selected, entries, destination, project=ROOT):
    """Publish a directory with portable files and a manifest written last."""
    if not selected:
        raise ValueError('请先勾选要带走的数据或模型。')
    destination = Path(destination)
    if not destination.is_dir():
        raise ValueError('请选择已存在的目标文件夹。')
    included, missing = with_training_data(selected, entries)
    folder = destination / f'EMG_离线实验包_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}'
    folder.mkdir(exist_ok=False)
    manifest = dict(format='emg-classroom-bundle', version=1, complete=False,
                    created_at=datetime.now().astimezone().isoformat(),
                    source=source_manifest(project), missing_training_record_ids=missing, files=[])
    try:
        for entry in included:
            subfolder = folder / ('recordings' if entry.kind == 'recording' else 'models')
            subfolder.mkdir(exist_ok=True)
            exported = export_entry(entry, subfolder)
            manifest['files'].append(dict(path=exported.relative_to(folder).as_posix(),
                sha256=file_hash(exported), kind=entry.kind, identity=entry.identity,
                target=entry.task.key, group=entry.meta['group'], name=entry.meta['name'],
                created_at=entry.meta.get('created_at'), training_record_ids=sorted(training_ids(entry))))
        instructions = (
            'EMG Lab 离线实验包\n\n'
            '本包包含数据和模型，不包含项目源码、Python 环境或 MuJoCo 资源。\n'
            '请同时取得教师提供的同版本源码与资源包。不要复制他人 .venv；按源码安装说明配置环境。\n\n'
            '1. 启动软件，进入“数据与模型”，点击“导入…”→“导入离线实验包文件夹”。\n'
            '2. 选择本文件所在目录；软件会校验文件校验和，复制到本机数据目录。\n'
            '3. 勾选数据后“用于训练”，或勾选一份数据“用于回放”；勾选模型可“使用模型”。\n'
            '4. 离线回放前断开采集设备，选择兼容模型。原始肌电重新经过模型推理，标签不控制机器人。\n'
            '5. 修改算法后重复使用同一留出数据比较；训练数据上的成绩不能当作独立测试成绩。\n\n'
            'manifest.json 保留文件校验和、记录/模型编号、训练数据关联和导出时源码指纹。\n'
            '源码指纹仅用于识别版本，不是运行前的强制限制；学生修改源码会产生新指纹。\n'
            '模型内历史训练路径可能来自教师电脑；通过 record_id 与清单关联，不依赖原绝对路径。\n'
            '本机能找到的关联训练数据已自动附带。缺失训练记录数：'+str(len(missing))+'。\n'
            '缺失关联训练数据不影响兼容模型的前向推理，但不能完整复现原训练。\n\n'
            '离线回放用于验证解码与场景响应，不能替代实时闭环控制或金币任务的课程考核。\n'
            '强度回归、七分类、逐指与协同控制需要相应采集协议和标签，现有标签不会自动补齐。\n')
        (folder/'阅读说明.txt').write_text(instructions, encoding='utf-8')
        guide = Path(project)/'docs/COURSE_GUIDE.md'
        if guide.is_file():
            (folder/'课堂与离线开发约定.md').write_bytes(guide.read_bytes())
        manifest['complete'] = True
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception:
        (folder/'导出未完成.txt').write_text('本包导出未完成，请重新导出。已有原始文件未修改。',encoding='utf-8')
        raise
    return folder, manifest


def bundle_files(folder):
    """Validate every manifest entry before any import; never follow outside paths."""
    folder = Path(folder).resolve()
    manifest_path = folder/'manifest.json'
    if manifest_path.stat().st_size > transfer.MAX_METADATA_BYTES:
        raise ValueError('实验包清单过大。')
    manifest = read_json(manifest_path)
    if (manifest.get('format') != 'emg-classroom-bundle' or manifest.get('version') != 1
            or not manifest.get('complete') or not isinstance(manifest.get('files'),list)
            or not 0 < len(manifest['files']) <= 1000):
        raise ValueError('这不是完整的 EMG 离线实验包。')
    result, seen = [], set()
    for item in manifest['files']:
        relative = Path(item['path'])
        path = (folder/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(folder) or path == folder or path in seen:
            raise ValueError('实验包包含不合法或重复的文件路径。')
        seen.add(path)
        limit = transfer.MAX_RECORD_BYTES if item['kind']=='recording' else transfer.MAX_MODEL_BYTES
        if path.stat().st_size > limit or file_hash(path) != item['sha256']:
            raise ValueError(f'文件校验失败：{relative}。请重新复制完整实验包。')
        entry = inspect_file(path)
        if (entry.kind != item['kind'] or entry.identity != item['identity']
                or entry.task.key != item['target']):
            raise ValueError(f'文件与清单不一致：{relative}。')
        result.append(path)
    return result, manifest


def describe(entry):
    m = entry.meta
    common = (f"{entry.task.title} · {m['name']} · {m['group']}\n"
              f"设备：{m.get('device')} · 传感器：{m.get('channel_ids')} · "
              f"采样率：{m.get('sampling_rate')} Hz · 单位：{m.get('unit')}\n"
              f"类别顺序：{' / '.join(entry.task.names)}\n")
    if entry.kind == 'recording':
        common += (f"时长：{m.get('duration',0):.1f} 秒 · 完整动作组：{m.get('completed_trials',0)} · "
                   + ('可用于训练' if usable_record(m) else '动作未采全，不能用于训练') + '\n')
    else:
        common += f"关联训练数据：{len(training_ids(entry))} 份 · 算法：{m.get('architecture','未知')}\n"
    notes=m.get('collection_notes',{})
    if isinstance(notes,dict):
        for key,title in [('operator','操作者'),('wearing','佩戴'),('channels','通道位置'),('actions','动作约定')]:
            if notes.get(key):common+=f"{title}：{notes[key]}\n"
    if m.get('rejected_trials'):
        common+='标记无效：'+'；'.join(f"第 {r['trial']} 组（{r['reason']}）" for r in m['rejected_trials'])+'\n'
        common+=f"可用完整动作组：{m.get('usable_trials',0)}\n"
    return common + f"编号：{entry.identity}\n位置：{entry.path}"
