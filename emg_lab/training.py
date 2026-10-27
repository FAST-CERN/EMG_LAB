"""EMG training with whole-trial splits, including training without holdout data."""
from __future__ import annotations
import copy
from datetime import datetime
import hashlib
from pathlib import Path
import uuid
import numpy as np
from .storage import read_recording, recording_metadata, usable_record, write_json, CLASSES, safe_name, excluded_trials
from .signal import SignalConfig, SignalFilter, compatible_profile, window_samples
from .tasks import task_from_metadata, require_task


def prepare_dataset(recordings):
    if not recordings:
        raise ValueError('请先勾选要训练的数据。')
    units, ids, hashes = [], set(), set()
    profile = None
    ordered = [(recording_metadata(p).get('created_at',''),str(p),Path(p)) for p in recordings]
    for _,_,folder in sorted(ordered):
        meta, raw, labels = read_recording(folder)
        if not usable_record(meta):
            raise ValueError(f"“{meta['name']}”没有可用的完整动作组，请检查无效标记或补采。")
        digest = hashlib.sha256(raw.tobytes()).hexdigest()
        if meta['record_id'] in ids or digest in hashes:
            raise ValueError('同一份数据被选择了两次，请取消重复项。')
        ids.add(meta['record_id'])
        hashes.add(digest)
        if profile is None:
            profile = meta
        task = task_from_metadata(profile)
        require_task(meta,task)
        class_count = len(task.classes)
        required = set(range(class_count))
        compatible_profile(profile,meta)
        if meta['group'] != profile['group'] or meta['preprocessing'] != profile['preprocessing']:
            raise ValueError('一次训练请选同一实验组、相同滤波设置的数据。')
        config = SignalConfig(**meta['preprocessing'])
        window, step = window_samples(meta['sampling_rate'],config)
        filtered = SignalFilter(meta['sampling_rate'],len(meta['channel_ids']),config).process(raw)
        # Legacy files label each action with a trial ID; keep that entire file together.
        modern = meta.get('schema_version',1)>=2
        trial_labels = [[r for r in labels if r['trial']==t] for t in sorted({r['trial'] for r in labels})] if modern else [labels]
        for segments in trial_labels:
            if any(r['trial'] in excluded_trials(meta) for r in segments):
                continue
            if {r['class_id'] for r in segments}!=required:
                continue  # Ignore the unfinished trial when a session was ended early.
            if modern and len(segments)!=class_count:
                raise ValueError('数据中的动作标签重复，请重新选择数据。')
            x,y,windows = [],[],[]
            for label in segments:
                start = label['start_sample']+round(.2*meta['sampling_rate'])
                for offset in range(start,label['end_sample']-window+1,step):
                    x.append(filtered[offset:offset+window].T)
                    y.append(label['class_id'])
                    windows.append([offset,offset+window])
            if set(y)!=required:
                raise ValueError('动作持续时间太短，请将每个动作设为至少 1 秒后重新采集。')
            units.append((np.stack(x),np.array(y,dtype=np.int64),dict(path=str(folder.resolve()),
                record_id=meta['record_id'],name=meta['name'],trial=segments[0]['trial'] if modern else None,
                collection_notes=meta.get('collection_notes',{}),
                unit='trial' if modern else 'legacy_session',sha256=digest,
                windows=len(y),sample_ranges=windows,class_counts=np.bincount(y,minlength=class_count).tolist())))
    if not units:
        raise ValueError('数据中还没有完整的一组动作，请按当前实验目标采全所有类别后再训练。')
    # Never randomly divide overlapping windows. One trial is still enough to train.
    n = len(units)
    n_val = max(1,round(n*.15)) if n>=2 else 0
    n_test = max(1,round(n*.15)) if n>=3 else 0
    n_train = n-n_val-n_test
    return profile,dict(train=units[:n_train],validation=units[n_train:n_train+n_val],test=units[n_train+n_val:])


def train(request, emit=lambda **event:None):
    import torch
    from torch import nn
    from .network import LiteCNN1D
    from .inference import StableCommand
    from .evaluation import evaluate_recordings
    torch.set_num_threads(2)
    torch.manual_seed(42)
    np.random.seed(42)
    emit(type='progress',stage='正在准备所选数据',progress=0)
    profile, groups = prepare_dataset(request['recordings'])
    task = task_from_metadata(profile)
    class_count = len(task.classes)
    arrays = {k:(np.concatenate([r[0] for r in v]),np.concatenate([r[1] for r in v])) for k,v in groups.items() if v}
    mean = arrays['train'][0].mean(axis=(0,2),keepdims=True)
    std = np.maximum(arrays['train'][0].std(axis=(0,2),keepdims=True),1e-8)
    data = {k:(torch.from_numpy((x-mean)/std),torch.from_numpy(y)) for k,(x,y) in arrays.items()}
    model = LiteCNN1D(len(profile['channel_ids']),arrays['train'][0].shape[2],class_count)
    optimizer = torch.optim.Adam(model.parameters(),lr=.001)
    loss_fn = nn.CrossEntropyLoss()
    epochs = int(request.get('epochs',30))
    if not 1 <= epochs <= 200:
        raise ValueError('训练轮数应在 1–200 之间。')
    best, best_loss, history = None, float('inf'), []
    def evaluate(x,y):
        model.eval()
        with torch.no_grad():
            logits = torch.cat([model(x[i:i+128]) for i in range(0,len(x),128)])
            return float(loss_fn(logits,y)),float((logits.argmax(1)==y).float().mean()),logits.argmax(1).numpy()
    x,y = data['train']
    for epoch in range(epochs):
        model.train()
        order = torch.randperm(len(x))
        loss_sum = 0.
        for start in range(0,len(x),64):
            idx = order[start:start+64]
            optimizer.zero_grad()
            loss = loss_fn(model(x[idx]),y[idx])
            if not torch.isfinite(loss):
                raise ValueError('训练损失异常，请检查电极信号和数据。')
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach())*len(idx)
        val_loss,val_accuracy = None,None
        if 'validation' in data:
            val_loss,val_accuracy,_ = evaluate(*data['validation'])
        history.append(dict(epoch=epoch+1,loss=loss_sum/len(x),val_loss=val_loss,val_accuracy=val_accuracy))
        if val_loss is None or val_loss < best_loss:
            # Without independent validation, export the final epoch, not a fake best score.
            best_loss = val_loss
            best = copy.deepcopy(model.state_dict())
        emit(type='progress',stage=f'训练 {epoch+1}/{epochs}',progress=(epoch+1)/epochs*.9,**history[-1])
    model.load_state_dict(best)
    val_accuracy = test_accuracy = confusion = None
    if 'validation' in data:
        _,val_accuracy,_ = evaluate(*data['validation'])
    if 'test' in data:
        _,test_accuracy,predictions = evaluate(*data['test'])
        confusion = np.zeros((class_count,class_count),dtype=int)
        np.add.at(confusion,(arrays['test'][1],predictions),1)
    class ExportModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model
            self.register_buffer('mean',torch.from_numpy(mean))
            self.register_buffer('std',torch.from_numpy(std))
        def forward(self,raw_filtered):
            return self.model((raw_filtered-self.mean)/self.std)
    title = request.get('name','方向分类模型').strip()
    now = datetime.now().astimezone()
    folder = Path(request['data_root'])/safe_name(profile['group'])/'models'/f'{now:%Y%m%d_%H%M%S}_{safe_name(title)}_{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True,exist_ok=False)
    bundle = ExportModel().eval()
    sample = torch.from_numpy(arrays['validation' if 'validation' in arrays else 'train'][0][:1])
    emit(type='progress',stage='正在保存模型',progress=.95)
    torch.onnx.export(bundle,sample,str(folder/'model.onnx'),input_names=['emg'],output_names=['logits'],
        opset_version=17,dynamo=False,dynamic_axes={'emg':{0:'batch'},'logits':{0:'batch'}})
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(folder/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    with torch.no_grad():
        expected = bundle(sample).numpy()
    np.testing.assert_allclose(session.run(None,{'emg':sample.numpy()})[0],expected,rtol=1e-4,atol=1e-4)
    metadata = {k:profile[k] for k in ('group','device','channel_ids','sampling_rate','unit','preprocessing')}
    metadata.update(schema_version=2,signal_type='emg',**task.metadata,
        name=title,model_id=folder.name,created_at=now.isoformat(),architecture='LiteCNN1D_channels_v2',
        backend_source='seeg_decode/3D_Model_Develop@eafcdc9',normalization='train_only_embedded_in_onnx',
        mean=mean.flatten().tolist(),std=std.flatten().tolist(),complete=True,
        split={k:[r[2] for r in v] for k,v in groups.items()},history=history,
        split_strategy='whole_trial_with_legacy_session_fallback',
        evaluation_status='test' if test_accuracy is not None else 'validation_only' if val_accuracy is not None else 'not_evaluated',
        validation_accuracy=val_accuracy,test_accuracy=test_accuracy,confusion_matrix=confusion.tolist() if confusion is not None else None,
        decision=StableCommand().settings)
    # Evaluate only after model selection/export, through the exact runtime.
    # Do not publish metadata.json until evaluation succeeds.
    emit(type='progress',stage='正在连续回放留出数据，检查最终指令',progress=.97)
    split = 'test' if groups['test'] else 'validation'
    metadata['online_evaluation'] = evaluate_recordings(folder,metadata,metadata['split'][split],split=split)
    write_json(folder/'metadata.json',metadata)
    emit(type='complete',path=str(folder),metadata=metadata,progress=1)
    return folder
