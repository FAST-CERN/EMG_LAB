"""Portable files must remain usable independently of their original location."""
import json
from pathlib import Path
import zipfile

import numpy as np
import onnx
import pytest

from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.storage import list_models, list_recordings, read_recording, read_json
from emg_lab.tasks import ROBOT, HAND
from emg_lab.training import train
from emg_lab.inference import InferencePipeline
from emg_lab import transfer
from conftest import synthesize


@pytest.fixture(scope='module', params=[ROBOT, HAND], ids=['robot', 'hand'])
def trained(tmp_path_factory, request):
    root = tmp_path_factory.mktemp(request.param.key)
    profile = dict(device='模拟练习', sampling_rate=1000., channel_ids=[1, 2, 3, 4], unit='a.u.')
    capture = CaptureRun(root, 'G03', '中文练习', profile, SignalConfig(),
                         trial_count=1, action_s=1.2, task=request.param)
    rng = np.random.default_rng(73)
    while not capture.completed:
        gain = np.full(4, .03)
        cue = capture.status()['command']
        if cue:
            gain[cue - 1] = 1.
        capture.feed((rng.normal(size=(20, 4)) * gain).astype(np.float32))
    model = train(dict(recordings=[capture.run_path],data_root=root,name='可迁移模型',epochs=2))
    return request.param, capture.run_path, model


def test_data_and_model_roundtrip_on_another_root(trained, tmp_path):
    task, recording, model = trained
    destination = tmp_path / 'U盘 作业'
    destination.mkdir()
    exported_data = transfer.export_recording(recording, destination, task)
    exported_model = transfer.export_model(model, destination, task)
    with zipfile.ZipFile(exported_model) as archive:
        assert set(archive.namelist()) == {'model.onnx', 'metadata.json'}
    data_result = transfer.import_recording(exported_data, tmp_path / '另一台电脑', task)
    model_result = transfer.import_model(exported_model, tmp_path / '另一台电脑', task)
    # Removing the transfer copies must not break the imported library.
    exported_data.unlink()
    exported_model.unlink()
    meta, raw, labels = read_recording(data_result.path)
    original, original_raw, original_labels = read_recording(recording)
    assert meta == original and labels == original_labels
    np.testing.assert_array_equal(raw, original_raw)
    expected = InferencePipeline(model, meta).feed(raw[:1000])
    actual = InferencePipeline(model_result.path, meta).feed(raw[:1000])
    np.testing.assert_allclose([r['probabilities'] for r in actual],
                               [r['probabilities'] for r in expected], rtol=1e-6)
    assert [r['filtered_class'] for r in actual] == [r['filtered_class'] for r in expected]
    assert len(list_recordings(tmp_path / '另一台电脑')) == 1
    assert len(list_models(tmp_path / '另一台电脑')) == 1


def test_duplicate_import_reuses_and_repeat_export_never_overwrites(trained, tmp_path):
    task, recording, model = trained
    a = transfer.import_recording(recording, tmp_path / 'library', task)
    b = transfer.import_recording(recording, tmp_path / 'library', task)
    m = transfer.import_model(model / 'model.onnx', tmp_path / 'library', task)
    n = transfer.import_model(model, tmp_path / 'library', task)
    assert not a.reused and b.reused and a.path == b.path
    assert not m.reused and n.reused and m.path == n.path
    first = transfer.export_model(m.path, tmp_path, task)
    previous = first.read_bytes()
    second = transfer.export_model(m.path, tmp_path, task)
    assert first != second and first.read_bytes() == previous
    assert read_json(n.path / 'metadata.json')['group'] == 'G03'


def test_wrong_target_and_corrupt_model_not_published(trained, tmp_path):
    task, recording, model = trained
    other = HAND if task == ROBOT else ROBOT
    with pytest.raises(ValueError, match='实验目标'):
        transfer.import_recording(recording, tmp_path / 'library', other)
    with pytest.raises(ValueError, match='实验目标'):
        transfer.import_model(model, tmp_path / 'library', other)
    bad = tmp_path / 'bad.emgmodel'
    with zipfile.ZipFile(bad, 'w') as archive:
        archive.writestr('model.onnx', b'not an onnx model')
        archive.writestr('metadata.json', (model / 'metadata.json').read_bytes())
    with pytest.raises(Exception):
        transfer.import_model(bad, tmp_path / 'library', task)
    assert not list_recordings(tmp_path / 'library')
    assert not list_models(tmp_path / 'library')


def test_reject_external_tensor_before_loading(trained, tmp_path):
    task, _, model = trained
    bad_model = onnx.load(model / 'model.onnx')
    tensor = bad_model.graph.initializer[0]
    tensor.ClearField('raw_data')
    tensor.data_location = onnx.TensorProto.EXTERNAL
    entry = tensor.external_data.add()
    entry.key, entry.value = 'location', '../outside.bin'
    bad = tmp_path / 'external.emgmodel'
    with zipfile.ZipFile(bad, 'w') as archive:
        archive.writestr('model.onnx', bad_model.SerializeToString())
        archive.writestr('metadata.json', (model / 'metadata.json').read_bytes())
    with pytest.raises(ValueError, match='外部权重'):
        transfer.import_model(bad, tmp_path / 'library', task)
    assert not list_models(tmp_path / 'library')


def test_reject_unsafe_members_and_oversize_without_writing(tmp_path, profile, monkeypatch):
    source = synthesize(tmp_path / 'source', profile, trial_count=1)[0]
    with zipfile.ZipFile(source) as archive:
        payload = {name: archive.read(name) for name in transfer.RECORD_MEMBERS}
    bad = tmp_path / 'bad.emg'
    with zipfile.ZipFile(bad, 'w') as archive:
        for name, value in payload.items():
            archive.writestr(name, value)
        archive.writestr('../outside.txt', 'unexpected')
    with pytest.raises(ValueError, match='格式'):
        transfer.import_recording(bad, tmp_path / 'library', ROBOT)
    assert not (tmp_path / 'outside.txt').exists()
    monkeypatch.setattr(transfer, 'MAX_RECORD_BYTES', 100)
    with pytest.raises(ValueError, match='过大'):
        transfer.import_recording(source, tmp_path / 'library', ROBOT)
    assert not (tmp_path / 'library').exists()


def test_legacy_import_and_data_validation(tmp_path, profile):
    source = synthesize(tmp_path / 'source', profile, trial_count=1)[0]
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    with zipfile.ZipFile(source) as archive:
        for name in transfer.RECORD_MEMBERS:
            (legacy / name).write_bytes(archive.read(name))
    meta = read_json(legacy / 'meta.json')
    meta['schema_version'] = 1
    (legacy / 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
    result = transfer.import_recording(legacy / 'emg.bin', tmp_path / 'library', ROBOT)
    assert result.path.suffix == '.emg'
    assert read_recording(result.path)[0]['schema_version'] == 1
    (legacy / 'labels.csv').write_text(
        'trial,start_sample,end_sample,class_id,class_name\n1,0,9999999,0,rest\n', encoding='utf-8')
    with pytest.raises(ValueError, match='标签'):
        transfer.import_recording(legacy, tmp_path / 'library', ROBOT)
    assert len(list_recordings(tmp_path / 'library')) == 1
