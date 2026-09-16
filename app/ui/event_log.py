"""Terminal-style event stream with pause / resume / clear / filter."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from . import style


class EventLogWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._paused = False
        self._filter = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        controls = QHBoxLayout()
        controls.setSpacing(3)
        self.pause_btn = QPushButton("PAUSE")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)
        clear_btn = QPushButton("CLEAR")
        clear_btn.clicked.connect(lambda: self.list.clear())
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("filter…")
        self.filter_edit.textChanged.connect(self._set_filter)
        controls.addWidget(self.pause_btn)
        controls.addWidget(clear_btn)
        controls.addWidget(self.filter_edit, 1)
        layout.addLayout(controls)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        layout.addWidget(self.list, 1)

    def _toggle_pause(self, on: bool) -> None:
        self._paused = on
        self.pause_btn.setText("RESUME" if on else "PAUSE")

    def _set_filter(self, text: str) -> None:
        self._filter = text.lower()

    def log(self, message: str, colour: str = style.TEXT) -> None:
        if self._paused:
            return
        if self._filter and self._filter not in message.lower():
            return
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        item = QListWidgetItem(f"{stamp}  {message}")
        item.setForeground(QColor(colour))
        self.list.insertItem(0, item)
        if self.list.count() > 500:
            self.list.takeItem(self.list.count() - 1)
