"""Show the real device page with live simulated EMG; no recording or DDS."""
import json
import sys
import time
from PySide6 import QtCore as C, QtWidgets as W
from emg_lab.app import MainWindow, configure_app
from emg_lab.storage import ROOT


def main():
    app = W.QApplication(sys.argv[:1])
    configure_app(app)
    window = MainWindow()
    window.stack.setCurrentIndex(1)
    window.tabs.setCurrentIndex(0)
    window.device_combo.setCurrentIndex(window.device_combo.findData('模拟练习'))
    window.show()
    window.activateWindow()
    window.guard(window.connect_device)
    started = None
    last_cue = None
    captured = False
    preview = C.QTimer(window)

    def update_preview():
        nonlocal started, last_cue, captured
        # Once the user starts another experiment, the regular workflow owns all cues.
        if window.session.capture or window.session.inference or window.scene_pending:
            preview.stop()
            return
        if window.tabs.currentIndex() != 0 or not window.device:
            if window.device:
                window.guard(lambda: window.device.send('cue', cue=0))
            preview.stop()
            return
        if not window.device_ready:
            return
        if started is None:
            started = time.monotonic()
            window.message('波形预览：模拟信号，CH1 周期性增强；可调整时间窗口、纵轴范围及原始／滤波显示。')
        elapsed = time.monotonic() - started
        cue = 1 if 1.2 <= elapsed % 4. < 2.4 else 0
        if cue != last_cue:
            window.guard(lambda: window.device.send('cue', cue=cue))
            last_cue = cue
        if elapsed >= 7.1 and not captured:
            captured = True
            output = ROOT/'local'
            output.mkdir(exist_ok=True)
            path = output/'device-waveform-preview.png'
            saved = window.grab().save(str(path))
            (output/'device-waveform-preview.json').write_text(json.dumps(dict(
                saved=saved, source='simulated', channels=window.session.profile['channel_ids'],
                sampling_rate=window.session.profile['sampling_rate'],
                curves=len(window.waveform.raw_curves)+len(window.waveform.filtered_curves),
                screenshot=str(path)), indent=2), encoding='utf-8')

    preview.timeout.connect(update_preview)
    preview.start(100)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
