"""Shared visual tokens for the classroom windows and offline help."""
import os
import sys
from pathlib import Path
from PySide6 import QtGui


def apply_theme(app):
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
    if font_path.exists():
        QtGui.QFontDatabase.addApplicationFont(str(font_path))
    if sys.platform == 'win32':
        # YaHei 只随 Windows 提供；其他平台沿用系统默认字体，避免为缺失字族付启动开销。
        app.setFont(QtGui.QFont('Microsoft YaHei UI', 10))
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    for role, color in (
        (QtGui.QPalette.Window, '#f3f5f9'), (QtGui.QPalette.WindowText, '#17243c'),
        (QtGui.QPalette.Base, '#ffffff'), (QtGui.QPalette.AlternateBase, '#f7f9fc'),
        (QtGui.QPalette.Text, '#17243c'), (QtGui.QPalette.Button, '#ffffff'),
        (QtGui.QPalette.ButtonText, '#17243c'), (QtGui.QPalette.Highlight, '#2957d5'),
        (QtGui.QPalette.HighlightedText, '#ffffff')):
        palette.setColor(role, QtGui.QColor(color))
    app.setPalette(palette)
    icons = Path(__file__).parent / 'icons'
    app.setStyleSheet("""
        QWidget { color:#17243c; font-size:14px; }
        QMainWindow,QDialog,QStackedWidget,QWidget#pageContent { background:#f3f5f9; }
        QLabel { background:transparent; border:none; }
        QLabel#heading { font-size:24px; font-weight:700; }
        QLabel#brand { font-size:20px; font-weight:700; letter-spacing:1px; }
        QLabel#hero { font-size:34px; font-weight:700; }
        QLabel#eyebrow { color:#2957d5; font-size:12px; font-weight:700; letter-spacing:2px; }
        QLabel#sectionTitle { font-size:16px; font-weight:700; }
        QLabel#fieldLabel { color:#475569; font-size:13px; font-weight:600; }
        QLabel#muted { color:#64748b; font-size:13px; }
        QFrame#card { background:#ffffff; border:1px solid #dde4ef; border-radius:12px; }
        QFrame#header { background:#ffffff; border-bottom:1px solid #dde4ef; }
        QFrame#actionBar { background:#ffffff; border-top:1px solid #dde4ef; }
        QLabel#notice { background:#eaf0ff; color:#27478c; border-radius:7px; padding:9px 14px; }
        QLabel#notice[tone="error"] { background:#fff0ed; color:#a8372a; }
        QLabel#status { color:#475569; background:#f1f5f9; border-radius:6px; padding:8px 12px; }
        QLabel#status[connected="true"] { background:#eaf7f0; color:#20704c; }
        QLabel#cueBanner,QLabel#prediction { background:#eef3ff; color:#2149b8;
            border:1px solid #dce6ff; border-radius:10px; padding:14px; font-size:25px; font-weight:600; }
        QLabel#prediction { font-size:28px; }
        QLabel#emptyState { color:#7b899e; background:#f8faff; border:1px dashed #ced8e8;
            border-radius:10px; padding:24px; }
        QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {
            background:#ffffff; border:1px solid #cdd7e6; border-radius:6px;
            padding:7px 10px; min-height:22px; selection-background-color:#2957d5; }
        QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus {
            border:1px solid #3563e9; background:#fcfdff; }
        QLineEdit:disabled,QComboBox:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled {
            color:#758298; background:#f4f6fa; border-color:#e2e8f0; }
        QComboBox { padding-right:26px; }
        QComboBox::drop-down { border:0; width:24px; }
        QComboBox::down-arrow { image:url("$DOWN"); width:12px; height:12px; }
        QComboBox QAbstractItemView { background:white; border:1px solid #cdd7e6;
            selection-background-color:#eaf0ff; selection-color:#2149b8; padding:4px; }
        QComboBox QAbstractItemView::item { min-height:30px; }
        QSpinBox,QDoubleSpinBox { padding-right:28px; }
        QSpinBox::up-button,QDoubleSpinBox::up-button { subcontrol-origin:border; subcontrol-position:top right;
            background:#f3f6fc; width:24px; border:0; border-top-right-radius:6px; }
        QSpinBox::down-button,QDoubleSpinBox::down-button { subcontrol-origin:border; subcontrol-position:bottom right;
            background:#f3f6fc; width:24px; border:0; border-bottom-right-radius:6px; }
        QSpinBox::up-arrow,QDoubleSpinBox::up-arrow { image:url("$UP"); width:12px; height:12px; }
        QSpinBox::down-arrow,QDoubleSpinBox::down-arrow { image:url("$DOWN"); width:12px; height:12px; }
        QPushButton { background:#ffffff; color:#334155; border:1px solid #cdd7e6;
            border-radius:7px; padding:8px 16px; min-height:22px; font-weight:500; }
        QPushButton:hover { background:#f0f4ff; border-color:#9fb4ef; color:#2149b8; }
        QPushButton:pressed,QPushButton:checked { background:#e2eaff; border-color:#7394ed; }
        QPushButton:focus { border:2px solid #6a8de9; padding:7px 15px; }
        QPushButton#primary { background:#2957d5; color:white; border:1px solid #2957d5; font-weight:600; }
        QPushButton#primary:hover { background:#2149b8; border-color:#2149b8; }
        QPushButton#primary:pressed { background:#1b3d9d; }
        QPushButton#danger { color:#b0443b; border-color:#e5bcb7; }
        QPushButton#danger:hover { background:#fff0ed; border-color:#cf7367; }
        QPushButton:disabled,QPushButton#primary:disabled,QPushButton#danger:disabled {
            background:#f0f3f8; color:#93a0b4; border:1px solid #e1e7f0; }
        QToolButton { background:transparent; color:#526987; border:0; padding:6px 2px; font-size:13px; }
        QToolButton:hover { color:#2957d5; }
        QCheckBox { spacing:8px; padding:4px 0; }
        QCheckBox:disabled { color:#758298; }
        QTabWidget::pane { border:0; }
        QTabBar::tab { background:#e9edf5; color:#61708a; border:0;
            border-bottom:3px solid transparent; padding:14px 25px; font-weight:600; }
        QTabBar::tab:hover { color:#2957d5; background:#e6edfd; }
        QTabBar::tab:selected { color:#2149b8; background:#ffffff; border-bottom:3px solid #2957d5; }
        QListWidget,QTableWidget,QPlainTextEdit,QTextBrowser { background:#ffffff; border:1px solid #dde4ef;
            border-radius:8px; padding:8px; selection-background-color:#e7eeff; selection-color:#2149b8; }
        QHeaderView::section { background:#edf2fc; color:#475569; font-weight:600; padding:9px 4px; border:0; }
        QTableWidget { alternate-background-color:#f7f9fd; }
        QTableWidget::item { padding:5px; border-bottom:1px solid #edf1f7; }
        QTableWidget::item:selected { background:#eaf0ff; color:#2149b8; }
        QDateEdit { background:white; border:1px solid #cdd7e6; border-radius:6px; padding:7px 10px; min-height:22px; }
        QMenu { background:white; border:1px solid #cdd7e6; padding:6px; }
        QMenu::item { padding:9px 20px; }
        QMenu::item:selected { background:#eaf0ff; color:#2149b8; }
        QListWidget::item { padding:10px 8px; border-radius:5px; }
        QListWidget::item:selected { background:#eaf0ff; color:#2149b8; }
        QListWidget::item:hover { background:#f3f6fc; }
        QPlainTextEdit { background:#f8faff; }
        QTextBrowser { padding:20px; }
        QProgressBar { border:0; background:#edf1f8; border-radius:5px;
            text-align:center; min-height:24px; color:#273b61; font-size:12px; }
        QProgressBar::chunk { background:#a8bff7; border-radius:5px; }
        QGroupBox { background:white; border:1px solid #dde4ef; border-radius:10px;
            margin-top:12px; padding:18px 12px 12px; font-weight:600; }
        QGroupBox::title { subcontrol-origin:margin; left:16px; padding:0 5px; }
        QScrollArea { border:0; background:transparent; }
        QScrollBar:vertical { background:#edf1f7; width:10px; margin:0; }
        QScrollBar::handle:vertical { background:#c1cbdb; border-radius:5px; min-height:36px; }
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
        QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background:transparent; }
        QToolTip { background:#17243c; color:white; border:0; padding:7px; }
    """.replace('$DOWN', (icons / 'chevron-down.svg').as_posix())
       .replace('$UP', (icons / 'chevron-up.svg').as_posix()))
