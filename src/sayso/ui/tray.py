"""System tray icon and menu. The tray is also the way to dictate when every hotkey is blocked."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from sayso.core.modes import USER_MODES, Mode
from sayso.ui import icons


class Tray(QObject):
    toggle_dictation = Signal()
    mode_chosen = Signal(object)  # Mode | None (automatic per app)
    always_listening = Signal(bool)
    pause_toggled = Signal(bool)
    offline_toggled = Signal(bool)
    open_history = Signal()
    open_settings = Signal()
    open_diagnostics = Signal()
    open_logs = Signal()
    quit_requested = Signal()

    def __init__(self, *, show_always_listening: bool, offline_locked: bool, managed: bool):
        super().__init__()
        self.icon = QSystemTrayIcon(icons.icon())
        self.icon.setToolTip("Sayso")
        menu = QMenu()
        self.menu = menu
        self.start_action = menu.addAction("Start dictation")
        self.start_action.triggered.connect(self.toggle_dictation)
        menu.addSeparator()

        style = menu.addMenu("Writing style")
        group = QActionGroup(style)
        group.setExclusive(True)
        auto = style.addAction("Automatic (per app)")
        auto.setCheckable(True)
        auto.setChecked(True)
        group.addAction(auto)
        auto.triggered.connect(lambda: self.mode_chosen.emit(None))
        self.mode_actions: dict[Mode | None, QAction] = {None: auto}
        for m in USER_MODES:
            a = style.addAction(m.label)
            a.setCheckable(True)
            group.addAction(a)
            a.triggered.connect(lambda _=False, mode=m: self.mode_chosen.emit(mode))
            self.mode_actions[m] = a

        self.always_action = menu.addAction("Always listening")
        self.always_action.setCheckable(True)
        self.always_action.setVisible(show_always_listening)
        self.always_action.toggled.connect(self.always_listening)
        self.pause_action = menu.addAction("Pause Sayso")
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(self.pause_toggled)
        self.offline_action = menu.addAction("Offline mode")
        self.offline_action.setCheckable(True)
        self.offline_action.setEnabled(not offline_locked)
        self.offline_action.toggled.connect(self.offline_toggled)
        menu.addSeparator()
        menu.addAction("History…").triggered.connect(self.open_history)
        menu.addAction("Settings…").triggered.connect(self.open_settings)
        menu.addAction("Diagnostics…").triggered.connect(self.open_diagnostics)
        menu.addAction("Open log folder").triggered.connect(self.open_logs)
        if managed:
            note = menu.addAction("Managed by your organization")
            note.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit Sayso").triggered.connect(self.quit_requested)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_history.emit()

    def set_state(self, *, recording: bool = False, paused: bool = False, offline: bool = False) -> None:
        badge = "recording" if recording else "offline" if offline else None
        self.icon.setIcon(icons.icon(badge, grey=paused))
        self.start_action.setText("Stop dictation" if recording else "Start dictation")

    def set_tooltip(self, text: str) -> None:
        self.icon.setToolTip(text)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        kind = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
        self.icon.showMessage(title, message, kind, 6000)

    def select_mode(self, mode: Mode | None) -> None:
        self.mode_actions[mode].setChecked(True)
