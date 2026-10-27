"""One SDK per process: Cometa uses .NET Framework, Delsys uses CoreCLR."""
from __future__ import annotations
import base64
import json
import os
import queue
import sys
import threading
import time
import traceback
import numpy as np
from .storage import ROOT, read_json


def main():
    config = json.loads(sys.argv[1])
    output = sys.stdout
    sys.stdout = sys.stderr  # SDK diagnostic prints must not corrupt the protocol.
    lock = threading.Lock()
    def emit(kind, **payload):
        with lock:
            output.write(json.dumps(dict(type=kind, **payload), ensure_ascii=False)+'\n')
            output.flush()
    commands = queue.Queue()
    frames = queue.Queue(maxsize=200)
    failed = threading.Event()
    def receive():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except ValueError:
                pass
        commands.put({'action':'shutdown'})
    threading.Thread(target=receive, daemon=True).start()
    channels = config['channel_ids']
    device = config['device']
    core = None
    cue = 0
    seq = 0
    rng = np.random.default_rng()
    def device_error(message):
        if not failed.is_set():
            emit('error',message=message)
            failed.set()
    def frame_callback(frame):
        try:
            if device == 'Cometa':
                data = np.asarray(frame.sensor_samples, dtype='<f4')[np.array(channels)-1].T.copy()
            else:
                order = [frame['pair_numbers'].index(c) for c in channels]
                data = np.asarray(frame['sensor_samples'], dtype='<f4')[order].T.copy()
            if len(data):
                frames.put_nowait((data,time.monotonic()))
        except Exception as exc:
            if not failed.is_set():
                emit('error', message=f'设备帧异常或队列溢出：{exc}')
                failed.set()
    try:
        if device == '模拟练习':
            rate = 1000.
        elif device == 'Cometa':
            from vendor.cometa.cometa_emg import CometaEMGCore
            core = CometaEMGCore(sensors=channels, enable_bus=False, on_frame=frame_callback, on_error=device_error, queue_maxsize=40)
            if not core.connect():
                raise RuntimeError(core.last_error or 'Cometa 连接失败，请检查基站、电极和驱动。')
            rate = 2000.
        elif device == 'Delsys':
            credentials = ROOT/'local'/'delsys.json'
            if credentials.exists():
                saved = read_json(credentials)
                os.environ['DELSYS_KEY'] = saved['DELSYS_KEY']
                os.environ['DELSYS_LICENSE'] = saved['DELSYS_LICENSE']
            from vendor.delsys.delsys_emg import DelsysEMGCore
            from .alignment import ChannelAligner
            class AlignedDelsys(DelsysEMGCore):
                def _extract_samples(self, data_out):
                    if not hasattr(self,'aligner'):
                        self.aligner = ChannelAligner(len(self._emg_channel_guids),round(self.sampling_rate_exact*2))
                    rows = []
                    for guid in self._emg_channel_guids:
                        try:
                            rows.append(list(data_out[guid]))
                        except KeyError:
                            rows.append([])
                    return self.aligner.push(rows)
            core = AlignedDelsys(sensors=channels, enable_bus=False, on_frame=frame_callback, on_error=device_error)
            action = config.get('action','connect')
            if action in ('scan','pair'):
                if not core.connect_base_only():
                    raise RuntimeError(core.last_error)
                if action == 'pair' and not core.pair_sensor(int(config['pair_number'])):
                    raise RuntimeError(core.last_error or '配对未完成。')
                sensors = core.scan_sensors()
                emit('sensors', sensors=[{'pair_number':s.pair_number, 'name':s.name, 'mode':s.mode} for s in sensors])
                return
            if not core.connect():
                raise RuntimeError(core.last_error or 'Delsys 连接失败。')
            if len(core._emg_channel_guids) != len(channels):
                raise RuntimeError('课堂版要求每个传感器一个 EMG 通道，请检查传感器模式。')
            rate = core.sampling_rate_exact
        else:
            raise ValueError('未知设备。')
        emit('connected', profile=dict(device=device, sampling_rate=rate, channel_ids=channels,
                                       unit='SDK raw' if device != '模拟练习' else 'a.u.'))
        if core is not None and not core.start():
            raise RuntimeError(getattr(core,'last_error','') or '启动采集失败。')
        next_frame = time.monotonic()
        while not failed.is_set():
            try:
                command = commands.get_nowait()
                if command['action'] == 'shutdown':
                    break
                if command['action'] == 'cue':
                    cue = int(command.get('cue',0))
            except queue.Empty:
                pass
            if device == '模拟练习':
                n = round(rate*.02)
                amplitude = np.full(len(channels), .04)
                if cue:
                    if cue <= len(channels):
                        amplitude[cue-1] = 1.0
                    else:
                        # Additional classes must not alias old classes on a four-channel mock.
                        amplitude = .04 + .65*np.array([(cue >> i)&1 for i in range(len(channels))])
                data = (rng.normal(size=(n,len(channels)))*amplitude).astype('<f4')
                next_frame += n/rate
                time.sleep(max(0, next_frame-time.monotonic()))
                captured_at = time.monotonic()
            else:
                try:
                    data,captured_at = frames.get(timeout=.05)
                except queue.Empty:
                    continue
            emit('frame', seq=seq, captured_at=captured_at, shape=list(data.shape), data=base64.b64encode(data.tobytes()).decode())
            seq += 1
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('error', message=str(exc))
    finally:
        if core is not None:
            try:
                core.stop()
                core.disconnect()
            except Exception:
                traceback.print_exc(file=sys.stderr)
        emit('closed')


if __name__ == '__main__':
    main()
