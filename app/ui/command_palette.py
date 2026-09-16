"""Ctrl+K command palette — a compact filterable command list."""

from __future__ import annotations

from typing import Callable, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QVBoxLayout


class CommandPalette(QDialog):
    def __init__(self, commands: List[Tuple[str, Callable]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.resize(420, 320)
        self._commands = commands

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command…")
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _: self._run())
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        self.search.installEventFilter(self)
        self._filter("")
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        text = text.lower()
        self.list.clear()
        self._visible = [c for c in self._commands if text in c[0].lower()]
        for label, _ in self._visible:
            self.list.addItem(label)
        if self._visible:
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        if obj is self.search and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow()
                self.list.setCurrentRow(max(0, row + (1 if key == Qt.Key.Key_Down else -1)))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run()
                return True
        return super().eventFilter(obj, event)

    def _run(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self._visible):
            self.accept()
            self._visible[row][1]()
