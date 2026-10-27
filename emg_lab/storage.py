"""Readable experiment names, collision-free directories, raw EMG and label storage."""
from __future__ import annotations

import csv
import json
import io
import re
import struct
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
from .tasks import task_from_metadata

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / 'data'
CLASSES = ['rest', 'left', 'right', 'forward']
CLASS_NAMES = ['停止', '左转', '右转', '前进']
HEADER = struct.Struct('<iiiii10s15sd')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def safe_name(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:64]
    if not value:
        raise ValueError('名称不能为空，也不能只包含空格或句点。')
    if value.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1,10)], *[f'LPT{i}' for i in range(1,10)]}:
        value = '_' + value
    return value


def new_run(root: Path, group: str, name: str, metadata: dict) -> Path:
    group_path, title = safe_name(group), safe_name(name)
    now = datetime.now().astimezone()
    identity = uuid.uuid4().hex[:8]
    path = Path(root) / group_path / 'recordings' / f'{now:%Y%m%d_%H%M%S}_{title}_{identity}'
    path.mkdir(parents=True, exist_ok=False)
    write_json(path / 'experiment.json', dict(metadata, experiment_id=identity, name=name.strip(), group=group.strip(), created_at=now.isoformat()))
    return path


class RecordingWriter:
    """Original EMG header layout, exact sampling rate and channel order in meta.json.

    Labels use sample indices (end exclusive), so wall-clock jitter cannot shift them.
    A session archive includes raw samples, metadata and sample-index labels.
    Training can use completed trials from an intentionally shortened session.
    """
    def __init__(self, folder: Path, metadata: dict, labels: list[dict], bundle=False):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=bundle)
        if (self.folder/'emg.bin').exists():
            raise FileExistsError('该数据文件已存在，请重新开始采集。')
        self.bundle = bundle
        self.output_path = Path(str(self.folder)+'.emg') if bundle else self.folder
        self.meta = dict(metadata, schema_version=metadata.get('schema_version',1), signal_type='emg', record_id=uuid.uuid4().hex, complete=False, finalized=False, samples=0)
        self.rate = float(metadata['sampling_rate'])
        self.channels = len(metadata['channel_ids'])
        self.count = 0
        self.labels = labels
        self.handle = (self.folder / 'emg.bin').open('wb')
        self.handle.write(b'\0' * HEADER.size)
        self.started = datetime.now().astimezone()
        self.meta['created_at'] = self.started.isoformat()
        self._header()
        write_json(self.folder / 'meta.json', self.meta)

    def _header(self):
        # Channel mask is retained for binary compatibility; channel_ids is authoritative.
        mask = sum(1 << (int(c)-1) for c in self.meta['channel_ids'] if str(c).isdigit() and 1 <= int(c) <= 31)
        self.handle.seek(0)
        self.handle.write(HEADER.pack(HEADER.size, self.channels, mask, round(self.rate), self.count,
            self.started.strftime('%Y-%m-%d').encode(), self.started.strftime('%H:%M:%S.%f')[:12].encode(), self.count/self.rate))
        self.handle.seek(0, 2)

    def append(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != self.channels or not np.isfinite(samples).all():
            raise ValueError('采集数据通道数不匹配或包含非有限值。')
        offsets = (np.arange(len(samples)) + self.count) / self.rate
        rows = np.column_stack([offsets, samples]).astype('<f4')
        self.handle.write(rows.tobytes())
        self.count += len(samples)

    def close(self, complete=False):
        if self.handle.closed:
            return
        self._header()
        self.handle.flush()
        self.handle.close()
        labels = [x for x in self.labels if x['end_sample'] <= self.count]
        with (self.folder / 'labels.csv').open('w', newline='', encoding='utf-8') as handle:
            fields = ['trial', 'start_sample', 'end_sample', 'class_id', 'class_name']
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(labels)
        self.meta.update(samples=self.count, duration=self.count/self.rate, complete=bool(complete),
                         finalized=True,labels=len(labels), created_at=self.started.isoformat())
        if self.meta['schema_version']>=2:
            trials = {r['trial'] for r in labels}
            required = set(range(len(task_from_metadata(self.meta).classes)))
            self.meta['completed_trials'] = sum({r['class_id'] for r in labels if r['trial']==t}==required for t in trials)
            rejected=excluded_trials(self.meta)
            self.meta['usable_trials'] = sum(t not in rejected and {r['class_id'] for r in labels if r['trial']==t}==required for t in trials)
        write_json(self.folder / 'meta.json', self.meta)
        if self.bundle:
            temporary = Path(str(self.output_path)+'.tmp')
            with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED) as archive:
                for name in ('emg.bin','labels.csv','meta.json'):
                    archive.write(self.folder/name,name)
            temporary.replace(self.output_path)
            # Only remove this capture's staging files after publishing the archive.
            for name in ('emg.bin','labels.csv','meta.json','experiment.json'):
                (self.folder/name).unlink(missing_ok=True)
            self.folder.rmdir()


def recording_metadata(path):
    path = Path(path)
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            return json.loads(archive.read('meta.json').decode('utf-8'))
    return read_json(path/'meta.json')


def usable_record(meta):
    if meta.get('schema_version',1)>=2:
        return meta.get('finalized',False) and meta.get('usable_trials',meta.get('completed_trials',0))>0
    return bool(meta.get('complete'))


def excluded_trials(meta):
    values=meta.get('rejected_trials',[])
    if not isinstance(values,list) or any(not isinstance(v,dict) or type(v.get('trial')) is not int or v['trial']<1 or not isinstance(v.get('reason'),str) for v in values):
        raise ValueError('无效动作组记录格式错误。')
    return {v['trial'] for v in values}


def read_recording(folder):
    folder = Path(folder)
    if folder.is_file():
        with zipfile.ZipFile(folder) as archive:
            meta = json.loads(archive.read('meta.json').decode('utf-8'))
            raw = archive.read('emg.bin')
            label_text = archive.read('labels.csv').decode('utf-8')
    else:
        meta = read_json(folder / 'meta.json')
        raw = (folder / 'emg.bin').read_bytes()
        label_text = (folder/'labels.csv').read_text(encoding='utf-8')
    if len(raw) < HEADER.size:
        raise ValueError('EMG 文件头不完整。')
    header = HEADER.unpack(raw[:HEADER.size])
    n = len(meta['channel_ids'])
    if header[0] != HEADER.size or header[1] != n or (len(raw)-HEADER.size) % (4*(n+1)):
        raise ValueError('EMG 文件头、通道信息或文件长度不匹配。')
    rows = np.frombuffer(raw, dtype='<f4', offset=HEADER.size).reshape(-1, n+1)
    if len(rows) != meta['samples'] or header[4] != len(rows):
        raise ValueError('EMG 文件尚未完整保存，或采样点数不匹配。')
    with io.StringIO(label_text,newline='') as handle:
        labels = [{**r, **{key:int(r[key]) for key in ('trial','start_sample','end_sample','class_id')}} for r in csv.DictReader(handle)]
    classes = task_from_metadata(meta).classes
    excluded_trials(meta)
    for label in labels:
        if label['trial']<1 or not 0 <= label['class_id'] < len(classes) or label['class_name'] != classes[label['class_id']] or not 0 <= label['start_sample'] < label['end_sample'] <= len(rows):
            raise ValueError('标签内容或采样点范围无效。')
    ordered = sorted(labels,key=lambda r:r['start_sample'])
    if any(a['end_sample']>b['start_sample'] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('数据中的动作标签有重叠，请重新选择数据。')
    if not np.isfinite(rows).all():
        raise ValueError('EMG 文件包含无效信号值。')
    return meta, rows[:,1:].copy(), labels


def list_recordings(root=DATA_ROOT):
    result = []
    paths = list(Path(root).glob('*/recordings/*.emg'))
    paths += [p.parent for p in Path(root).glob('*/recordings/*/round-*/meta.json')]
    for path in paths:
        try:
            meta = recording_metadata(path)
            result.append((path, meta))
        except (OSError, ValueError,zipfile.BadZipFile,KeyError):
            continue
    return sorted(result, key=lambda x:x[1].get('created_at',''), reverse=True)


def record_label(meta):
    trials = f"{meta.get('completed_trials',0)} 组动作" if meta.get('schema_version',1)>=2 else f"数据 {meta.get('round',1)}"
    suffix = '' if meta.get('complete') else ' [提前结束]' if usable_record(meta) else ' [动作未采全]'
    if meta.get('rejected_trials'):
        suffix+=f" [标记无效 {len(excluded_trials(meta))} 组]"
    device = '模拟设备' if meta['device']=='模拟练习' else meta['device']
    return f"{meta['name']} · {meta['group']} · {trials} · {device} · {meta.get('created_at','')[:19].replace('T',' ')}"+suffix


def list_models(root=DATA_ROOT):
    result = []
    for path in Path(root).glob('*/models/*/metadata.json'):
        try:
            meta = read_json(path)
            if meta.get('complete') and (path.parent / 'model.onnx').is_file():
                result.append((path.parent, meta))
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda x:x[1]['created_at'], reverse=True)
