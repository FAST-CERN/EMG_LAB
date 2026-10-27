"""Evaluate the exported model through the real online filter and state machine."""
import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto
from emg_lab.capture import CaptureRun
from emg_lab.signal import SignalConfig
from emg_lab.storage import CLASSES
from emg_lab.training import prepare_dataset


def constant_model(tmp_path, threshold):
    profile = dict(device='模拟练习', sampling_rate=1000., channel_ids=[1,2], unit='a.u.')
    # Deliberately off the global 100 ms grid: evaluation must not require
    # exact equality with training windows anchored to each action start.
    capture = CaptureRun(tmp_path,'TEST','评估',profile,SignalConfig(),trial_count=3,
                         action_s=1.23,prepare_s=.17)
    capture.feed(np.zeros((capture.session_length,2),np.float32))
    _, groups = prepare_dataset([capture.run_path])
    folder = tmp_path/'model';folder.mkdir()
    logits = np.log([[.01,.52,.01,.46]]).astype(np.float32)
    node = helper.make_node('Constant', [], ['logits'], value=numpy_helper.from_array(logits))
    graph = helper.make_graph([node], 'uncertain_left',
        [helper.make_tensor_value_info('emg',TensorProto.FLOAT,[1,2,500])],
        [helper.make_tensor_value_info('logits',TensorProto.FLOAT,[1,4])])
    model = helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)])
    model.ir_version = 10
    onnx.save(model,folder/'model.onnx')
    metadata = dict(profile,preprocessing=SignalConfig().to_dict(),complete=True,
                    signal_type='emg',classes=CLASSES,decision=dict(threshold=threshold,hold=3))
    return folder,metadata,[r[2] for r in groups['test']]


def test_confident_argmax_does_not_masquerade_as_a_final_left_command(tmp_path):
    from emg_lab.evaluation import evaluate_recordings, evaluation_details
    folder,meta,units = constant_model(tmp_path,.65)
    report = evaluate_recordings(folder,meta,units,split='test')
    assert report['scored_windows'] > 0 and report['trial_count'] == 1
    assert report['raw']['per_class'][1]['recall'] == 1.
    assert report['command']['per_class'][1]['recall'] == 0.
    assert report['command']['per_class'][0]['recall'] == 1.
    text = evaluation_details(dict(meta,online_evaluation=report))
    assert '最终指令' in text and '左转' in text and '未正确输出' in text


def test_continuous_context_and_saved_decision_settings_are_used(tmp_path):
    from emg_lab.evaluation import evaluate_recordings
    folder,meta,units = constant_model(tmp_path,.50)
    report = evaluate_recordings(folder,meta,units,split='test')
    # Preparation has already supplied many windows: resetting the gate for
    # each label would incorrectly lose the first two correct left outputs.
    assert report['command']['per_class'][1]['recall'] == 1.
    assert report['decision'] == meta['decision']


def test_legacy_score_is_not_presented_as_final_command_quality():
    from emg_lab.evaluation import evaluation_text, evaluation_details
    meta = dict(test_accuracy=.95,validation_accuracy=.98)
    assert '窗口分类' in evaluation_text(meta)
    assert '尚未评估最终指令' in evaluation_details(meta)
