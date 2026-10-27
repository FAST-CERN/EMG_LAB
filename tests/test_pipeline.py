import threading
import time
import numpy as np
import pytest
from emg_lab.inference import InferencePipeline,StableCommand
from emg_lab.training import train,prepare_dataset
from emg_lab.storage import read_json,read_recording
from emg_lab.robot import DdsBroadcast
from emg_lab.processes import DeviceProcess
from conftest import synthesize


def test_train_onnx_streaming_matches_batch_and_train_only_statistics(tmp_path,records,profile):
    path=train(dict(recordings=records,data_root=tmp_path,name='自检模型',epochs=12))
    meta=read_json(path/'metadata.json')
    _,split=prepare_dataset(records)
    np.testing.assert_allclose(meta['mean'],split['train'][0][0].mean(axis=(0,2)),atol=1e-7)
    assert meta['complete'] and len(meta['history'])==12
    assert 0<=meta['test_accuracy']<=1
    assert meta['architecture']=='LiteCNN1D_channels_v2'
    assert meta['online_evaluation']['split']=='test'
    assert meta['online_evaluation']['decision']==meta['decision']==dict(threshold=.65,hold=3)
    raw=read_recording(records[-1])[1]
    full=InferencePipeline(path,profile).feed(raw)
    stream=InferencePipeline(path,profile)
    chunked=[]
    for block in np.array_split(raw,97):
        chunked.extend(stream.feed(block))
    assert len(full)==len(chunked)>20
    np.testing.assert_allclose([x['probabilities'] for x in full],[x['probabilities'] for x in chunked],atol=1e-6)
    assert [x['filtered_class'] for x in full]==[x['filtered_class'] for x in chunked]
    with pytest.raises(ValueError):
        InferencePipeline(path,dict(profile,channel_ids=[4,3,2,1]))


@pytest.mark.parametrize('count',[1,2])
def test_small_sessions_export_usable_model_without_invented_test_score(tmp_path,profile,count):
    records=synthesize(tmp_path,profile,trial_count=count)
    path=train(dict(recordings=records,data_root=tmp_path,name='少量数据',epochs=2))
    meta=read_json(path/'metadata.json')
    assert meta['test_accuracy'] is None and meta['confusion_matrix'] is None
    assert meta['evaluation_status']==('not_evaluated' if count==1 else 'validation_only')
    if count==1:
        assert meta['online_evaluation'] is None
        assert meta['validation_accuracy'] is None
        assert all(x['val_accuracy'] is None for x in meta['history'])
    else:
        assert meta['online_evaluation']['split']=='validation'
    assert InferencePipeline(path,profile).feed(read_recording(records[0])[1])


def test_stable_command_requires_persistence_and_low_confidence_stops():
    state=StableCommand()
    assert [state.update([.01,.97,.01,.01]) for _ in range(3)]==[0,0,1]
    assert state.update([.25,.25,.25,.25])==0
    assert [state.update([.01,.01,.01,.97]) for _ in range(3)]==[0,0,3]
    assert state.update([.98,.01,.005,.005])==0


def test_dds_guard_timeout_and_shutdown():
    class Fake:
        last_error=''
        def __init__(self):self.sent=[];self.closed=False
        def connect(self):return True
        def send_direction(self,event):self.sent.append(event);return True
        def disconnect(self):self.closed=True
    now=[10.]
    adapter=Fake()
    dds=DdsBroadcast(adapter=adapter,clock=lambda:now[0])
    for source,device in [('replay','Cometa'),('live','模拟练习')]:
        with pytest.raises(ValueError):dds.start(source,device)
    dds.update({'filtered_class':1,'probabilities':[.01,.97,.01,.01]})
    dds.publish_once()
    assert adapter.sent[-1]['filtered_class']==1
    now[0]+=1.1
    dds.publish_once()
    assert adapter.sent[-1]['filtered_class']==0
    dds.close()
    assert adapter.closed and adapter.sent[-1]['filtered_class']==0


def test_original_adapter_wire_mapping_without_broadcast():
    from bsi_robot_base import UnitreeDdsHumanoidRobotAdapter
    class Publisher:
        def __init__(self):self.values=[]
        def publish(self,command,confidence):self.values.append((command,confidence))
    adapter=UnitreeDdsHumanoidRobotAdapter()
    publisher=Publisher()
    adapter._publisher=publisher
    for cls in range(4):
        p=[0.,0.,0.,0.];p[cls]=1.
        assert adapter.send_direction({'filtered_class':cls,'probabilities':p})
    assert [x[0] for x in publisher.values]==[0,2,3,1]


def test_mock_device_subprocess_connect_stream_and_shutdown():
    ready=threading.Event()
    messages=[]
    def callback(event):
        messages.append(event)
        if event['type']=='frame':ready.set()
    process=DeviceProcess(dict(device='模拟练习',channel_ids=[1,2,3,4]),callback)
    try:
        assert ready.wait(15),messages
        frame=next(x for x in messages if x['type']=='frame')
        assert frame['samples'].shape==(20,4)
        process.send('cue',cue=3)
    finally:
        process.close()
    assert process.process.poll() is not None
