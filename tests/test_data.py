import shutil
import zipfile
import json
import numpy as np
import pytest
from emg_lab.alignment import ChannelAligner
from emg_lab.capture import CaptureRun, preparation_countdown
from emg_lab.signal import SignalConfig,SignalFilter,compatible_profile
from emg_lab.storage import new_run,read_recording,safe_name,read_json,write_json,list_recordings,recording_metadata,usable_record,RecordingWriter
from emg_lab.training import prepare_dataset
from conftest import synthesize


def test_rest_countdown_matches_sample_clock(tmp_path, profile):
    capture = CaptureRun(tmp_path, 'TEST', '倒计时', profile, SignalConfig(), trial_count=1,
                         action_s=1., prepare_s=1., rest_s=1.)
    try:
        capture.feed(np.zeros((2500, 4), dtype=np.float32))
        status = capture.status()
        assert status['phase'] == '休息' and status['remaining'] == .5
        assert status['command'] == 0 and status['cue'] == 3
        capture.feed(np.zeros((500, 4), dtype=np.float32))
        status = capture.status()
        assert status['phase'] == '准备' and status['remaining'] == 1.
        assert status['cue'] == 0 and status['action_index'] == 2
    finally:
        capture.stop()


def test_source_timing_cues_and_trainable_sample_boundaries(tmp_path, profile):
    capture = CaptureRun(tmp_path, 'TEST', '源流程', profile, SignalConfig(), trial_count=1)
    try:
        assert capture.session_length == 32000  # four actions, each 3 s preparation + 5 s active
        assert preparation_countdown(capture.status()) == 3
        for count, digit in [(1000, 2), (1000, 1), (700, 0)]:
            status = capture.feed(np.zeros((count, 4), dtype=np.float32))
            assert preparation_countdown(status) == digit
            assert status['phase'] == '准备' and status['command'] == 0
        status = capture.feed(np.zeros((300, 4), dtype=np.float32))
        assert status['phase'] == '动作' and status['command'] == 3
        assert preparation_countdown(status) is None
        status = capture.feed(np.zeros((5000, 4), dtype=np.float32))
        assert status['phase'] == '准备' and status['cue'] == 0
        assert status['remaining'] == 3.  # no extra rest segment
        capture.feed(np.zeros((24000, 4), dtype=np.float32))
        assert capture.completed
        meta, raw, labels = read_recording(capture.run_path)
        assert len(raw) == 32000
        assert (meta['prepare_seconds'], meta['action_seconds'], meta['rest_seconds']) == (3., 5., 0.)
        assert [(x['start_sample'], x['end_sample'], x['class_id']) for x in labels] == [
            (3000, 8000, 3), (11000, 16000, 0), (19000, 24000, 1), (27000, 32000, 2)]
    finally:
        capture.stop()


def test_names_do_not_overwrite_and_stay_in_group(tmp_path):
    a = new_run(tmp_path,'第一组','右手/练习',{})
    b = new_run(tmp_path,'第一组','右手/练习',{})
    assert a!=b and a.parent==b.parent and a.is_dir() and b.is_dir()
    assert a.is_relative_to(tmp_path)
    assert read_json(a/'experiment.json')['name']=='右手/练习'
    assert safe_name('CON')=='_CON'
    with pytest.raises(ValueError):
        safe_name('...')


def test_one_session_file_balanced_trials_and_disjoint_splits(records):
    assert len(records)==1 and records[0].is_file() and records[0].suffix=='.emg'
    assert len(list(records[0].parent.iterdir()))==1
    meta,groups = prepare_dataset(records)
    seen=[]
    for group in groups.values():
        for x,y,source in group:
            seen.append((source['record_id'],source['trial']))
            assert x.shape[1:]==(4,500)
            assert set(y)=={0,1,2,3}
    assert len(set(seen))==3
    ranges = {k:[r for _,_,s in v for r in s['sample_ranges']] for k,v in groups.items()}
    assert max(r[1] for r in ranges['train']) <= min(r[0] for r in ranges['validation'])
    assert max(r[1] for r in ranges['validation']) <= min(r[0] for r in ranges['test'])
    for path in records:
        m,x,labels=read_recording(path)
        assert m['complete'] and len(x)==m['samples']
        assert all(x['end_sample']<=m['samples'] for x in labels)
        assert m['completed_trials']==m['trial_count']==3
        for trial in range(1,4):
            assert [x['class_id'] for x in labels if x['trial']==trial]==[3,0,1,2]


@pytest.mark.parametrize('count,expected',[(1,(1,0,0)),(2,(1,1,0)),(3,(1,1,1)),(7,(5,1,1))])
def test_any_positive_trial_count_can_train(tmp_path,profile,count,expected):
    paths=synthesize(tmp_path,profile,trial_count=count)
    _,groups=prepare_dataset(paths)
    assert tuple(len(groups[k]) for k in ('train','validation','test'))==expected
    assert list_recordings(tmp_path)[0][0]==paths[0]


def test_incomplete_and_duplicate_records_rejected(tmp_path,profile,records):
    c=CaptureRun(tmp_path,'X','中断',profile,SignalConfig(),trial_count=1)
    c.feed(np.ones((800,4),dtype=np.float32))
    c.stop()
    incomplete=c.run_path
    assert not read_recording(incomplete)[0]['complete']
    with pytest.raises(ValueError,match='完整动作'):
        prepare_dataset([incomplete])
    duplicate=tmp_path/'duplicate.emg'
    shutil.copy2(records[0],duplicate)
    with pytest.raises(ValueError,match='重复'):
        prepare_dataset([records[0],duplicate])


def test_early_finish_retains_completed_trial_for_training(tmp_path,profile):
    c=CaptureRun(tmp_path,'TEST','提前结束',profile,SignalConfig(),trial_count=3,action_s=1.)
    c.feed(np.random.default_rng(1).normal(size=(c.trial_length+c.segment_length+100,4)))
    c.stop()
    meta=recording_metadata(c.run_path)
    assert not meta['complete'] and meta['completed_trials']==1 and usable_record(meta)
    _,groups=prepare_dataset([c.run_path])
    assert len(groups['train'])==1 and not groups['validation'] and not groups['test']


def test_legacy_recordings_remain_readable_and_trainable(tmp_path,profile):
    path=tmp_path/'TEST'/'recordings'/'old'/'round-01'
    labels=[dict(trial=i+1,start_sample=i*1200,end_sample=(i+1)*1200,class_id=i,class_name=name) for i,name in enumerate(['rest','left','right','forward'])]
    w=RecordingWriter(path,dict(profile,name='旧数据',group='TEST',round=1,preprocessing=SignalConfig().to_dict()),labels)
    w.append(np.random.default_rng(7).normal(size=(4800,4)))
    w.close(complete=True)
    _,groups=prepare_dataset([path])
    assert len(groups['train'])==1 and groups['train'][0][2]['unit']=='legacy_session'
    assert list_recordings(tmp_path)[0][0]==path


def test_filter_chunk_invariance_and_model_profile(profile):
    raw=np.random.default_rng(9).normal(size=(5031,4))
    config=SignalConfig()
    expected=SignalFilter(1000,4,config).process(raw)
    f=SignalFilter(1000,4,config)
    actual=np.concatenate([f.process(x) for x in np.array_split(raw,17)])
    np.testing.assert_allclose(expected,actual,atol=1e-7)
    for change in ({'channel_ids':[2,1,3,4]},{'device':'Cometa'},{'sampling_rate':2000},{'unit':'V'}):
        with pytest.raises(ValueError):
            compatible_profile(profile,dict(profile,**change))


def test_delsys_alignment_never_truncates_surplus():
    a=ChannelAligner(2,200)
    np.testing.assert_array_equal(a.push([[1,2,3],[11]]),[[1],[11]])
    np.testing.assert_array_equal(a.push([[4],[12,13,14]]),[[2,3,4],[12,13,14]])
    assert a.push([[],[15]]) is None
    np.testing.assert_array_equal(a.push([[5],[]]),[[5],[15]])
    with pytest.raises(ValueError):
        a.push([[1]*201,[]])


def test_corrupt_bin_rejected(records):
    path=records[0]
    with zipfile.ZipFile(path) as archive:
        contents={n:archive.read(n) for n in archive.namelist()}
    contents['emg.bin']+=b'bad'
    with zipfile.ZipFile(path,'w') as archive:
        for name,content in contents.items():archive.writestr(name,content)
    with pytest.raises(ValueError):
        read_recording(records[0])
