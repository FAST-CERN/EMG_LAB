"""Small layout primitives; application state belongs in app.py."""
from PySide6 import QtWidgets as W


def text_label(text, role='muted'):
    widget = W.QLabel(text)
    widget.setWordWrap(True)
    widget.setObjectName(role)
    return widget


def card(title=None):
    widget = W.QFrame()
    widget.setObjectName('card')
    layout = W.QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    if title:
        layout.addWidget(text_label(title, 'sectionTitle'))
    return widget, layout


def field(title, control):
    widget = W.QWidget()
    layout = W.QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    caption = text_label(title, 'fieldLabel')
    caption.setBuddy(control)
    layout.addWidget(caption)
    layout.addWidget(control)
    return widget


def fields(*pairs):
    layout = W.QHBoxLayout()
    layout.setSpacing(16)
    for title, control in pairs:
        layout.addWidget(field(title, control), 1)
    return layout
