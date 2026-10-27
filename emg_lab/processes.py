"""Small JSON-lines process boundary for devices and training."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import numpy as np
from .storage import ROOT


class JsonProcess:
    def __init__(self, module, argument, callback):
        self.callback = callback
        self.closing = False
        self.lock = threading.Lock()
        self.seq = 0
        log_dir = ROOT/'local'
        log_dir.mkdir(exist_ok=True)
        self.log = (log_dir/(module.split('.')[-1]+'.log')).open('w', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable,'-u','-m',module,argument], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, encoding='utf-8', env=dict(os.environ, PYTHONIOENCODING='utf-8'),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                event = json.loads(line)
                event['process_id'] = self.process.pid
                if event['type']=='frame':
                    if time.monotonic()-event['captured_at'] > 1.:
                        raise ValueError('设备帧积压超过 1 秒，当前任务已停止。')
                    if event['seq'] != self.seq:
                        raise ValueError('设备数据序列不连续，已停止本次任务。')
                    self.seq += 1
                    event['samples'] = np.frombuffer(base64.b64decode(event.pop('data')),dtype='<f4').reshape(event['shape']).copy()
                if not self.closing:
                    self.callback(event)
        except Exception as exc:
            if not self.closing:
                self.callback(dict(type='error', message=str(exc),process_id=self.process.pid))
                if self.process.poll() is None:
                    self.process.terminate()
        finally:
            self.process.wait()
            self.log.close()
            if not self.closing:
                self.callback(dict(type='exited', returncode=self.process.returncode,process_id=self.process.pid))

    def send(self, action, **args):
        if self.closing or self.process.poll() is not None:
            return
        with self.lock:
            self.process.stdin.write(json.dumps(dict(action=action, **args))+'\n')
            self.process.stdin.flush()

    def close(self):
        if self.closing:
            return
        try:
            self.send('shutdown')
        except (OSError, ValueError):
            pass
        self.closing = True
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)


class DeviceProcess(JsonProcess):
    def __init__(self, config, callback):
        super().__init__('emg_lab.device_worker',json.dumps(config),callback)
