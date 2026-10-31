"""Searchable list of past dictations with copy, insert-again, transcript and delete."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sayso.core.history import History, HistoryItem
from sayso.ui import theme


def _when(ts: float) -> str:
    d = time.time() - ts
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if time.strftime("%Y%m%d", time.localtime(ts)) == time.strftime("%Y%m%d"):
        return time.strftime("Today %H:%M", time.localtime(ts))
    return time.strftime("%d %b %H:%M", time.localtime(ts))


class _Card(QWidget):
    def __init__(self, item: HistoryItem):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(3)
        meta = QLabel(
            f"{_when(item.created)}  ·  {item.app or 'unknown app'}  ·  {item.mode.replace('_mode', '').replace('_', ' ')}"
            f"  ·  {item.latency_ms / 1000:.1f} s"
        )
        theme.set_prop(meta, "muted")
        body = QLabel("\n".join(item.text.splitlines()[:2]) or "(empty)")
        body.setWordWrap(True)
        lay.addWidget(meta)
        lay.addWidget(body)


class HistoryWindow(QWidget):
    insert_again = Signal(str)

    def __init__(self, history: History, retention_days: Callable[[], int] = lambda: 30):
        super().__init__()
        self.history = history
        self._retention = retention_days
        self.setObjectName("surface")
        self.setWindowTitle("Sayso history")
        self.resize(560, 640)
        self._items: list[HistoryItem] = []

        self.search = QLineEdit(placeholderText="Search your dictations")
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.copy_btn = QPushButton("Copy")
        self.insert_btn = QPushButton("Insert again")
        self.transcript_btn = QPushButton("Show transcript")
        self.delete_btn = QPushButton("Delete")
        theme.set_prop(self.delete_btn, "danger")
        self.clear_btn = QPushButton("Clear all")
        theme.set_prop(self.clear_btn, "danger")
        self.footer = QLabel("")
        theme.set_prop(self.footer, "muted")

        actions = QHBoxLayout()
        for b in (self.copy_btn, self.insert_btn, self.transcript_btn, self.delete_btn):
            actions.addWidget(b)
        foot = QHBoxLayout()
        foot.addWidget(self.footer, 1)
        foot.addWidget(self.clear_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addLayout(actions)
        lay.addLayout(foot)

        self._debounce = QTimer(self, singleShot=True, interval=200)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.copy_btn.clicked.connect(self._copy)
        self.insert_btn.clicked.connect(lambda: self._with_item(lambda i: self.insert_again.emit(i.text)))
        self.transcript_btn.clicked.connect(self._show_transcript)
        self.delete_btn.clicked.connect(self._delete)
        self.clear_btn.clicked.connect(self._clear)
        self.refresh()

    def refresh(self) -> None:
        self._items = self.history.recent(query=self.search.text().strip())
        self.list.clear()
        for it in self._items:
            row = QListWidgetItem()
            card = _Card(it)
            row.setSizeHint(card.sizeHint())
            row.setData(Qt.ItemDataRole.UserRole, it.id)
            self.list.addItem(row)
            self.list.setItemWidget(row, card)
        note = (
            "History is off."
            if not self.history.enabled
            else f"Kept for {self._retention()} days on this computer."
            if self._retention() > 0
            else "Kept until you clear it."
        )
        self.footer.setText(f"{len(self._items)} dictations · {note}")
        self._sync_buttons()

    def _selected(self) -> HistoryItem | None:
        row = self.list.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _with_item(self, fn: Callable[[HistoryItem], None]) -> None:
        item = self._selected()
        if item:
            fn(item)

    def _sync_buttons(self) -> None:
        has = self._selected() is not None
        for b in (self.copy_btn, self.insert_btn, self.transcript_btn, self.delete_btn):
            b.setEnabled(has)
        self.clear_btn.setEnabled(bool(self._items))

    def _copy(self) -> None:
        self._with_item(lambda i: QGuiApplication.clipboard().setText(i.text))

    def _show_transcript(self) -> None:
        self._with_item(
            lambda i: QMessageBox.information(
                self,
                "What you said",
                f"{i.transcript}\n\nSpeech engine: {i.stt_engine}\nWriter: {i.llm_provider}",
            )
        )

    def _delete(self) -> None:
        self._with_item(lambda i: (self.history.delete(i.id), self.refresh()))

    def _clear(self) -> None:
        if (
            QMessageBox.question(self, "Clear history", "Delete all saved dictations?")
            == QMessageBox.StandardButton.Yes
        ):
            self.history.clear()
            self.refresh()
