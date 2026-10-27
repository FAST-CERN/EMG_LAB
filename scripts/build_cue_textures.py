"""Build deterministic classroom UI text assets; requires Windows YaHei font."""
from pathlib import Path
import sys,os,json,hashlib
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6 import QtCore as C,QtGui as G,QtWidgets as W
ROOT=Path(__file__).resolve().parents[1]
def main():
    app=W.QApplication.instance() or W.QApplication([])
    font_id=G.QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'))
    if font_id<0:raise RuntimeError('Cannot load Microsoft YaHei; do not publish missing-glyph textures.')
    font=G.QFont('Microsoft YaHei');font.setPixelSize(44)
    names=dict(rest='停止',left='左转',right='右转',forward='前进',backward='后退',strafe_left='左移',strafe_right='右移')
    folder=ROOT/'assets/classroom';generated={}
    for prefix in ('cue','action'):
        for key,name in names.items():
            if prefix=='cue' and key in ('rest','left','right','forward'):continue
            text=('准备：' if prefix=='cue' else '动作：')+name
            image=G.QImage(280,76,G.QImage.Format_ARGB32);image.fill(C.Qt.transparent)
            painter=G.QPainter(image);painter.setRenderHint(G.QPainter.Antialiasing)
            painter.setBrush(G.QColor('#10151f'));painter.setPen(C.Qt.NoPen);painter.drawRoundedRect(image.rect(),12,12)
            painter.setFont(font);painter.setPen(G.QColor('white'));painter.drawText(image.rect(),C.Qt.AlignCenter,text);painter.end()
            path=folder/f'{prefix}_{key}.png'
            # The existing MuJoCo billboard is mirrored on its visible side.
            assert image.flipped(C.Qt.Orientation.Horizontal).save(str(path))
            generated[path.name]=dict(text=text,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (folder/'extended_cues_provenance.json').write_text(json.dumps(dict(generator='scripts/build_cue_textures.py',
        description='Locally rendered interface labels; straight arrows reuse the supplied forward mesh with body-frame rotation.',files=generated),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Generated',len(generated),'text badges')
if __name__=='__main__':main()
