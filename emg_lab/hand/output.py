"""Optional direct Damiao USB output; never constructed by the 3D preview."""
import queue
import time
from PySide6 import QtCore as C
from ..tasks import HAND_RATE


class HardwareLease:
    """Share exclusivity with the standalone pose and gesture validation GUIs."""
    def __init__(self):
        import sys
        self.handle=None
        if sys.platform=='win32':
            import ctypes
            self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
            self.kernel.CreateMutexW.restype=ctypes.c_void_p
            self.kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            self.handle=self.kernel.CreateMutexW(None,False,'Local\\Revo2PoseGui_Damiao_21108DD0')
            if not self.handle or ctypes.get_last_error()==183:
                self.close()
                raise RuntimeError('已有 Revo2 控制窗口打开，请先关闭该窗口。')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle=None


class HandOutput(C.QObject):
    changed=C.Signal(str)
    failed=C.Signal(str)
    sample=C.Signal(dict)

    def __init__(self,parent=None,controller_factory=None,lease_factory=HardwareLease):
        super().__init__(parent)
        self.controller_factory=controller_factory
        self.lease_factory=lease_factory
        self.controller=None
        self.lease=None
        self.initialized=False
        self.connected=False
        self.enabled=False
        self.error=''
        self._status=''
        self.pending_initialization=False
        self.last_command=None
        self.updated=0.
        self.timer=C.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.poll)

    def enable(self,source,device):
        if source!='live' or device not in ('Cometa','Delsys'):
            raise ValueError('真机控制需要真实肌电设备的实时信号；模拟和回放只驱动屏幕预览。')
        if not self.connected: raise ValueError('请先连接灵巧手，等待连接成功。')
        self.enabled=True
        self.last_command=None
        self.updated=time.monotonic()
        if not self.initialized:
            self.pending_initialization=self.controller.interrupted()
            if not self.pending_initialization: self.controller.request_intent('open')
            self.status('正在恢复初始姿态：拇指默认位置、四指张开；完成后接收肌电指令。')
        else:
            self.status('真机控制已启用 · 75 %/s')

    def status(self,text):
        if text != self._status:
            self._status=text
            self.changed.emit(text)

    def connect_hand(self):
        if self.controller: raise ValueError('灵巧手已经连接。')
        try:
            self.lease=self.lease_factory()
            factory=self.controller_factory
            if factory is None:
                from .driver.revo2_path_control import PathController
                factory=PathController
            self.controller=factory()
            self.controller.set_speed(HAND_RATE)
            self.controller.start()
            self.controller.connect_event.set()
            self.initialized=False
            self.connected=self.enabled=False
            self.error=''
            self.last_command=None
            self.timer.start()
            self.status('正在连接灵巧手…')
        except Exception:
            self.close()
            raise

    def update(self,result):
        command=result['filtered_class']
        if command not in (0,1,2): raise ValueError('不是有效的灵巧手三类指令。')
        if not self.controller or not self.enabled or not self.initialized: return
        self.updated=time.monotonic()
        if command and self.controller.interrupted(): return
        if command==self.last_command: return
        self.last_command=command
        if command==0:
            self.controller.request_stop()
        else:
            self.controller.request_intent('open' if command==1 else 'fist')

    def poll(self):
        controller=self.controller
        if controller is None: return
        controller.heartbeat_tick()
        while True:
            try: event=controller.events.get_nowait()
            except queue.Empty: break
            kind=event['kind']
            if kind=='connected':
                self.connected=True
                self.status('左手已连接 · 待机；开始推理后才启用动作输出。')
            elif kind=='sample':
                self.initialized=event['view']['initialized']
                self.sample.emit(event['sample'])
                if self.enabled and self.initialized:
                    self.status('真机控制已启用 · 75 %/s · 拇指保持默认姿态')
            elif kind=='stopped' and not self.enabled:
                self.status('四指停止已确认 · 连接保留，可再次开始推理。')
            elif kind=='error':
                message=event['message']
                self.close(notify=False)
                self.error=message + ('；'+self.error if self.error else '')
                self.failed.emit(self.error)
                return
        if self.enabled and self.pending_initialization and not controller.interrupted():
            self.pending_initialization=False
            controller.request_intent('open')
        if self.enabled and self.initialized and self.last_command not in (None,0) and time.monotonic()-self.updated>1.:
            controller.request_stop()
            self.last_command=0
            self.status('肌电指令已过期，四指已请求停止。')

    def disable(self):
        was_enabled,self.enabled=self.enabled,False
        self.pending_initialization=False
        self.last_command=None
        if self.controller and was_enabled:
            self.controller.request_stop()
            self.status('已暂停输出，正在确认停止…')

    def close(self,notify=True):
        self.timer.stop()
        self.enabled=False
        self.pending_initialization=False
        controller,self.controller=self.controller,None
        if controller:
            controller.quit_event.set()
            if controller.is_alive(): controller.join()
            errors=[]
            while True:
                try: event=controller.events.get_nowait()
                except queue.Empty: break
                if event['kind']=='error': errors.append(event['message'])
            if errors: self.error='；'.join(errors)
        if self.lease:
            self.lease.close(); self.lease=None
        self.initialized=False
        self.connected=False
        self.last_command=None
        if notify and self.error: self.failed.emit(self.error)
        return self.error
