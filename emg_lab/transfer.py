"""Persistent classroom imports and self-contained, non-overwriting exports.

Only the documented recording/model members are copied; archives are never
extracted to paths supplied by the archive. No Python/pickle model is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
import uuid
import zipfile

import numpy as np

from .storage import list_models, list_recordings, read_recording, safe_name
from .tasks import require_task

RECORD_MEMBERS = ('emg.bin', 'labels.csv', 'meta.json')
MODEL_MEMBERS = ('model.onnx', 'metadata.json')
MAX_RECORD_BYTES = 512 * 1024 * 1024
MAX_MODEL_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ImportResult:
    path: Path
    reused: bool = False


def _read_members(source, members, limit):
    source = Path(source)
    if source.is_dir():
        sizes = [(source / name).stat().st_size for name in members]
        if sum(sizes) > limit or sizes[-1] > MAX_METADATA_BYTES:
            raise ValueError('文件过大，请分批采集或使用较小的模型。')
        return {name: (source / name).read_bytes() for name in members}
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) != len(members) or {i.filename for i in infos} != set(members):
            raise ValueError('文件包内容不完整或格式不正确，请选择本软件导出的文件。')
        if sum(i.file_size for i in infos) > limit or archive.getinfo(members[-1]).file_size > MAX_METADATA_BYTES:
            raise ValueError('文件包解压后过大，请分批采集或使用较小的模型。')
        return {name: archive.read(name) for name in members}


def _metadata(payload, name, task):
    meta = json.loads(payload[name].decode('utf-8'))
    require_task(meta, task)
    if meta.get('signal_type') != 'emg':
        raise ValueError('请选择本软件保存的肌电数据或模型。')
    for key in ('name', 'group', 'device', 'unit', 'created_at'):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise ValueError(f'文件信息缺少有效的 {key} 字段。')
    safe_name(meta['group'])
    safe_name(meta['name'])
    channels = meta.get('channel_ids')
    if not isinstance(channels, list) or not channels or len(channels) != len(set(channels)):
        raise ValueError('文件的传感器编号为空或重复。')
    from .signal import SignalConfig, SignalFilter, window_samples
    config = SignalConfig(**meta['preprocessing'])
    SignalFilter(meta['sampling_rate'], len(channels), config)
    window_samples(meta['sampling_rate'], config)
    return meta


def _fingerprint(payload):
    digest = hashlib.sha256()
    for name, value in sorted(payload.items()):
        digest.update(name.encode())
        digest.update(len(value).to_bytes(8, 'little'))
        digest.update(value)
    return digest.digest()


def _record_source(source):
    source = Path(source)
    return source.parent if source.name.lower() == 'emg.bin' else source


def _record_payload(source, task):
    source = _record_source(source)
    payload = _read_members(source, RECORD_MEMBERS, MAX_RECORD_BYTES)
    meta = _metadata(payload, 'meta.json', task)
    if not isinstance(meta.get('record_id'), str) or not meta['record_id'].strip():
        raise ValueError('数据缺少记录编号，无法用于训练和溯源。')
    if meta.get('schema_version', 1) >= 2 and not meta.get('finalized'):
        raise ValueError('这份数据尚未保存完成，请先结束采集。')
    # Validate exactly the bytes to be copied, including binary header and labels.
    with tempfile.TemporaryDirectory(prefix='emg-import-check-') as folder:
        for name, value in payload.items():
            (Path(folder) / name).write_bytes(value)
        read_recording(Path(folder))
    return payload, meta


def _has_external_tensor(message):
    """Inspect protobuf fields without loading external ONNX tensor locations."""
    import onnx
    if isinstance(message, onnx.TensorProto) and (message.external_data or message.data_location == onnx.TensorProto.EXTERNAL):
        return True
    for field, value in message.ListFields():
        if field.message_type:
            children = value if field.is_repeated else (value,)
            if any(_has_external_tensor(child) for child in children):
                return True
    return False


def _model_payload(source, task):
    source = Path(source)
    if source.suffix.lower() == '.onnx':
        if source.name.lower() != 'model.onnx':
            raise ValueError('请选择模型目录中的 model.onnx，或选择 .emgmodel 模型包。')
        source = source.parent
    payload = _read_members(source, MODEL_MEMBERS, MAX_MODEL_BYTES)
    meta = _metadata(payload, 'metadata.json', task)
    if not meta.get('complete') or not meta.get('model_id'):
        raise ValueError('模型未训练完成或缺少模型编号。')
    import onnx
    model = onnx.load_model_from_string(payload['model.onnx'])
    if _has_external_tensor(model):
        raise ValueError('模型引用了外部权重文件，请先导出为权重内嵌的单文件 ONNX 模型。')
    onnx.checker.check_model(model)
    from .inference import InferencePipeline
    with tempfile.TemporaryDirectory(prefix='emg-model-check-') as folder:
        for name, value in payload.items():
            (Path(folder) / name).write_bytes(value)
        pipeline = InferencePipeline(Path(folder), meta)
        result = pipeline.feed(np.zeros((pipeline.window, len(meta['channel_ids'])), dtype=np.float32))
        if len(result) != 1:
            raise ValueError('模型无法处理当前配置的一个信号窗口。')
    return payload, meta


def _existing(root, payload, entries, members, limit):
    fingerprint = _fingerprint(payload)
    for path, _ in entries(root):
        try:
            if _fingerprint(_read_members(path, members, limit)) == fingerprint:
                return path
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            continue
    return None


def _write_archive(payload, destination, title, suffix):
    destination = Path(destination)
    if not destination.is_dir():
        raise ValueError('请选择一个已经存在且可写的目标文件夹。')
    # Exclusive creation also protects existing files if two exports race.
    while True:
        output = destination / f'{safe_name(title)}_{uuid.uuid4().hex[:8]}{suffix}'
        try:
            handle = output.open('xb')
            break
        except FileExistsError:
            continue
    try:
        with handle, zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in payload.items():
                archive.writestr(name, value)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return output


def import_recording(source, root, task):
    payload, meta = _record_payload(source, task)
    existing = _existing(root, payload, list_recordings, RECORD_MEMBERS, MAX_RECORD_BYTES)
    if existing is not None:
        return ImportResult(existing, reused=True)
    destination = Path(root) / safe_name(meta['group']) / 'recordings'
    destination.mkdir(parents=True, exist_ok=True)
    output = _write_archive(payload, destination, meta['name'], '.emg')
    return ImportResult(output)


def export_recording(source, destination, task):
    payload, meta = _record_payload(source, task)
    return _write_archive(payload, destination, meta['name'], '.emg')


def import_model(source, root, task):
    payload, meta = _model_payload(source, task)
    existing = _existing(root, payload, list_models, MODEL_MEMBERS, MAX_MODEL_BYTES)
    if existing is not None:
        return ImportResult(existing, reused=True)
    parent = Path(root) / safe_name(meta['group']) / 'models'
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / f'{safe_name(meta["name"])}_{uuid.uuid4().hex[:8]}'
    # Validate before publication; metadata is written last so incomplete models
    # do not appear in the existing model browser.
    destination.mkdir(exist_ok=False)
    try:
        for name in MODEL_MEMBERS:
            (destination / name).write_bytes(payload[name])
    except BaseException:
        for name in MODEL_MEMBERS:
            (destination / name).unlink(missing_ok=True)
        destination.rmdir()
        raise
    return ImportResult(destination)


def export_model(source, destination, task):
    payload, meta = _model_payload(source, task)
    return _write_archive(payload, destination, meta['name'], '.emgmodel')
