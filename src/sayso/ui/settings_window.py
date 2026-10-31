"""Settings dialog. Every control is bound to a dotted settings key; keys the IT policy sets are shown
disabled with a tooltip. Saving writes settings.json (never policy keys, never API keys)."""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sayso.core.config import AppProfile, LoadedSettings, ProviderSettings, Settings
from sayso.core.modes import USER_MODES
from sayso.ui import theme
from sayso.winsys.hotkey_logic import Chord

LOCKED_TIP = "Set by your organization"
PROVIDER_KINDS = ["anthropic", "openai", "azure", "openrouter", "ollama", "lmstudio", "local", "custom", "offline"]
FW_MODELS = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3-turbo"]
STT_ENGINES = ["faster_whisper", "whisper_cpp", "windows_speech", "cloud"]
INJECTION_METHODS = ["auto", "paste", "clipboard", "accessibility", "keyboard"]


@dataclass
class SettingsServices:
    """Things the dialog needs from the rest of the app; defaults keep it usable (and testable) on its own."""

    devices: Callable[[], list[tuple[str, str]]] = lambda: []
    stt_status: Callable[[], list[tuple[str, str]]] = lambda: []
    diagnostics: Callable[[], dict[str, Any]] = lambda: {}
    test_provider: Callable[[str, ProviderSettings, str | None], tuple[bool, int, str]] | None = None
    calibrate: Callable[[], float | None] | None = None
    download_model: Callable[[str, Callable[[float], None]], str] | None = None
    last_foreground_process: Callable[[], str] = lambda: ""
    pause_hotkeys: Callable[[bool], None] = lambda paused: None
    autostart_get: Callable[[], bool] = lambda: False
    autostart_set: Callable[[bool], None] = lambda on: None
    secret_present: Callable[[str], bool] = lambda ref: False
    secret_set: Callable[[str, str | None], None] = lambda ref, value: None
    data_dir: str = ""
    delete_history: Callable[[], None] = lambda: None
    fix_hints: dict[str, str] = field(default_factory=dict)


def _get(data: dict, dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        cur = cur[part]
    return cur


def _set(data: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = value


class ShortcutEdit(QWidget):
    changed = Signal(str)

    def __init__(self, pause: Callable[[bool], None]):
        super().__init__()
        self._pause = pause
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.btn = QPushButton("Record")
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {theme.DANGER};")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, 1)
        row.addWidget(self.btn)
        self.btn.clicked.connect(self._start)
        self._recording = False
        self._mods: set[str] = set()

    def text(self) -> str:
        return self.edit.text()

    def setText(self, t: str) -> None:  # noqa: N802
        self.edit.setText(t)

    def setEnabled(self, on: bool) -> None:  # noqa: N802
        super().setEnabled(on)

    def _start(self) -> None:
        self._recording = True
        self.btn.setText("Press keys…")
        self._pause(True)
        self.grabKeyboard()

    def _finish(self) -> None:
        self.releaseKeyboard()
        self._pause(False)
        self._recording = False
        self.btn.setText("Record")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self._recording:
            return super().keyPressEvent(event)
        name = _qt_key_name(event.key())
        if name in {"ctrl", "alt", "shift", "win"}:
            self._mods.add(name)
            return
        mods = [m for m in ("ctrl", "alt", "shift", "win") if m in self._mods or _has_mod(event, m)]
        spec = "+".join([*mods, name]) if name else ""
        self._mods.clear()
        self._finish()
        try:
            Chord.parse(spec)
        except ValueError as exc:
            self.edit.setToolTip(str(exc))
            return
        self.edit.setText(spec)
        self.changed.emit(spec)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if self._recording and _qt_key_name(event.key()) in self._mods and len(self._mods) == 1:
            # a lone modifier (e.g. right ctrl) is a valid chord
            spec = next(iter(self._mods))
            self._mods.clear()
            self._finish()
            self.edit.setText(spec)
            self.changed.emit(spec)


def _has_mod(event, name: str) -> bool:
    flag = {"ctrl": Qt.KeyboardModifier.ControlModifier, "alt": Qt.KeyboardModifier.AltModifier,
            "shift": Qt.KeyboardModifier.ShiftModifier, "win": Qt.KeyboardModifier.MetaModifier}[name]
    return bool(event.modifiers() & flag)


def _qt_key_name(key: int) -> str:
    K = Qt.Key
    table = {K.Key_Control: "ctrl", K.Key_Alt: "alt", K.Key_Shift: "shift", K.Key_Meta: "win", K.Key_Space: "space",
             K.Key_Escape: "esc", K.Key_CapsLock: "capslock", K.Key_Tab: "tab", K.Key_Return: "enter",
             K.Key_Backspace: "backspace", K.Key_Delete: "delete", K.Key_Insert: "insert", K.Key_Home: "home",
             K.Key_End: "end", K.Key_PageUp: "pageup", K.Key_PageDown: "pagedown", K.Key_Left: "left",
             K.Key_Right: "right", K.Key_Up: "up", K.Key_Down: "down"}
    if key in table:
        return table[key]
    if K.Key_F1 <= key <= K.Key_F24:
        return f"f{key - K.Key_F1 + 1}"
    if 0x30 <= key <= 0x39 or 0x41 <= key <= 0x5A:
        return chr(key).lower()
    return ""


class _OrderedList(QWidget):
    """Reorderable list of (name, enabled) rows."""

    def __init__(self, labels: dict[str, str] | None = None):
        super().__init__()
        self.labels = labels or {}
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        up, down = QPushButton("Up"), QPushButton("Down")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        col = QVBoxLayout()
        col.addWidget(up)
        col.addWidget(down)
        col.addStretch(1)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.list, 1)
        row.addLayout(col)
        self.up_btn, self.down_btn = up, down

    def set_items(self, enabled: list[str], extra: list[str]) -> None:
        self.list.clear()
        for name in [*enabled, *[e for e in extra if e not in enabled]]:
            it = QListWidgetItem(self.labels.get(name, name))
            it.setData(Qt.ItemDataRole.UserRole, name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if name in enabled else Qt.CheckState.Unchecked)
            self.list.addItem(it)

    def enabled(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def set_status(self, name: str, text: str) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == name:
                it.setText(f"{self.labels.get(name, name)}   —   {text}")

    def _move(self, d: int) -> None:
        r = self.list.currentRow()
        if r < 0 or not 0 <= r + d < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + d, it)
        self.list.setCurrentRow(r + d)


class _KeyValueTable(QTableWidget):
    def __init__(self, headers: tuple[str, str]):
        super().__init__(0, 2)
        self.setHorizontalHeaderLabels(list(headers))
        self.horizontalHeader().setStretchLastSection(True)
        self.setColumnWidth(0, 220)
        self.verticalHeader().hide()

    def load(self, data: dict[str, str]) -> None:
        self.setRowCount(0)
        for k, v in data.items():
            self.add_row(k, v)

    def add_row(self, k: str = "", v: str = "") -> None:
        r = self.rowCount()
        self.insertRow(r)
        self.setItem(r, 0, QTableWidgetItem(k))
        self.setItem(r, 1, QTableWidgetItem(v))

    def remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(r)

    def dump(self) -> dict[str, str]:
        out = {}
        for r in range(self.rowCount()):
            k = (self.item(r, 0).text() if self.item(r, 0) else "").strip()
            v = self.item(r, 1).text() if self.item(r, 1) else ""
            if k:
                out[k] = v
        return out


class SettingsWindow(QDialog):
    saved = Signal(object)  # Settings
    _tested = Signal(bool, int, str)
    _calibrated = Signal(object)
    _progress = Signal(float)
    _downloaded = Signal(str)

    def __init__(self, loaded: LoadedSettings, services: SettingsServices | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.loaded = loaded
        self.svc = services or SettingsServices()
        self.setWindowTitle("Sayso settings")
        self.resize(720, 560)
        self.setMinimumSize(640, 480)
        self._data: dict[str, Any] = loaded.settings.to_dict()
        self._bindings: list[tuple[str, Callable[[], Any], Callable[[Any], None], QWidget]] = []
        self._providers: dict[str, ProviderSettings] = copy.deepcopy(loaded.settings.llm.providers)
        self._current_provider = ""
        self._pending_keys: dict[str, str] = {}

        self.nav = QListWidget()
        self.nav.setFixedWidth(160)
        self.stack = QStackedWidget()
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(f"color: {theme.TIDE};")
        self.banner.hide()
        pages = [("General", self._page_general), ("Shortcuts", self._page_shortcuts),
                 ("Microphone", self._page_mic), ("Speech engine", self._page_stt), ("AI", self._page_ai),
                 ("Apps", self._page_apps), ("Words", self._page_words), ("Privacy", self._page_privacy),
                 ("Diagnostics", self._page_diag)]
        for name, builder in pages:
            self.nav.addItem(name)
            self.stack.addWidget(builder())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.save_btn = QPushButton("Save")
        theme.set_prop(self.save_btn, "primary")
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn.clicked.connect(self.save)
        self.cancel_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.save_btn)
        body = QHBoxLayout()
        body.addWidget(self.nav)
        right = QVBoxLayout()
        right.addWidget(self.banner)
        right.addWidget(self.stack, 1)
        body.addLayout(right, 1)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addLayout(buttons)

        self._tested.connect(self._show_test)
        self._calibrated.connect(self._apply_calibration)
        self._progress.connect(lambda v: self.dl_bar.setValue(int(v * 100)))
        self._downloaded.connect(self._download_done)
        self.load_values()

    # -- binding

    def bind(self, widget: QWidget, dotted: str) -> QWidget:
        if isinstance(widget, QCheckBox):
            get, set_ = widget.isChecked, widget.setChecked
        elif isinstance(widget, QComboBox):
            def get() -> Any:
                data = widget.currentData()
                if dotted == "audio.device":
                    return data or None
                return data if data is not None else widget.currentText()

            def set_(v: Any) -> None:
                i = widget.findData(v)
                if i < 0:
                    i = widget.findText(str(v))
                if i < 0 and widget.isEditable():
                    widget.setEditText(str(v))
                elif i >= 0:
                    widget.setCurrentIndex(i)
        elif isinstance(widget, (QSpinBox, QSlider)):
            get, set_ = widget.value, widget.setValue
        elif isinstance(widget, ShortcutEdit):
            get, set_ = widget.text, widget.setText
        elif isinstance(widget, QLineEdit):
            get, set_ = (lambda: widget.text().strip() or None) if dotted == "audio.device" else widget.text, widget.setText
        else:
            raise TypeError(type(widget))
        self._bindings.append((dotted, get, set_, widget))
        return widget

    def load_values(self) -> None:
        for dotted, _, set_, widget in self._bindings:
            try:
                value = _get(self._data, dotted)
            except KeyError:
                continue
            set_("" if value is None else value)
            locked = self.loaded.is_locked(dotted)
            widget.setEnabled(not locked)
            if locked:
                widget.setToolTip(LOCKED_TIP)

    def collect(self) -> Settings:
        data = copy.deepcopy(self._data)
        for dotted, get, _, _widget in self._bindings:
            if not self.loaded.is_locked(dotted):
                _set(data, dotted, get())
        data["stt"]["engines"] = self.stt_order.enabled()
        data["llm"]["chain"] = self.chain_list.enabled()
        self._store_provider()
        data["llm"]["providers"] = {n: json.loads(json.dumps(p.__dict__)) for n, p in self._providers.items()}
        data["profiles"] = self._dump_profiles()
        data["vocabulary"] = self.vocab.dump()
        data["snippets"] = self.snippets.dump()
        data["privacy"]["blocked_apps"] = _lines(self.blocked.toPlainText())
        data["privacy"]["no_cloud_apps"] = _lines(self.no_cloud.toPlainText())
        data["injection"]["app_overrides"] = {k: v for k, v in self.overrides.dump().items() if v in INJECTION_METHODS}
        for key in ("stt.engines", "llm.chain", "llm.providers", "profiles", "vocabulary", "snippets",
                    "privacy.blocked_apps", "privacy.no_cloud_apps", "injection.app_overrides"):
            if self.loaded.is_locked(key):
                _set(data, key, _get(self.loaded.settings.to_dict(), key))
        return Settings.from_dict(data)

    def save(self) -> None:
        new = self.collect()
        for ref, value in self._pending_keys.items():
            self.svc.secret_set(ref, value)
        self._pending_keys.clear()
        self.svc.autostart_set(self.autostart.isChecked())
        self.saved.emit(new)
        self.accept()

    def show_welcome(self, text: str) -> None:
        self.banner.setText(text)
        self.banner.show()

    # -- page helpers

    def _page(self, title: str, intro: str = "") -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        h = QLabel(title)
        theme.set_prop(h, "heading")
        lay.addWidget(h)
        if intro:
            t = QLabel(intro)
            t.setWordWrap(True)
            theme.set_prop(t, "muted")
            lay.addWidget(t)
        return w, lay

    @staticmethod
    def _combo(items: list[tuple[str, str]] | list[str], editable: bool = False) -> QComboBox:
        c = QComboBox()
        c.setEditable(editable)
        for it in items:
            label, data = (it, it) if isinstance(it, str) else it
            c.addItem(label, data)
        return c

    # -- pages

    def _page_general(self) -> QWidget:
        w, lay = self._page("General")
        form = QFormLayout()
        mode = self._combo([(m.label, m.value) for m in USER_MODES])
        form.addRow("Default writing style", self.bind(mode, "general.default_mode"))
        form.addRow("Show the overlay", self.bind(QCheckBox(), "general.show_overlay"))
        form.addRow("Overlay position", self.bind(self._combo([("Bottom of screen", "bottom"), ("Top of screen", "top")]),
                                                 "general.overlay_position"))
        form.addRow("Play sounds", self.bind(QCheckBox(), "general.sounds"))
        self.autostart = QCheckBox()
        self.autostart.setChecked(self.svc.autostart_get())
        form.addRow("Start with Windows", self.autostart)
        lay.addLayout(form)
        where = QLabel(f"Your data lives in: {self.svc.data_dir or 'this folder'}")
        theme.set_prop(where, "muted")
        where.setWordWrap(True)
        lay.addWidget(where)
        lay.addStretch(1)
        return w

    def _page_shortcuts(self) -> QWidget:
        w, lay = self._page("Shortcuts", "Hold the push-to-talk keys while you speak. Use the toggle to start and stop "
                                       "hands-free. Hold the edit key with either to change selected text by voice.")
        form = QFormLayout()
        self.shortcut_edits: dict[str, ShortcutEdit] = {}
        for label, key in (("Push to talk", "hotkeys.push_to_talk"), ("Toggle (press to start, again to stop)", "hotkeys.toggle"),
                           ("Always listening on/off", "hotkeys.always_listening"), ("Edit-selection key", "hotkeys.command_modifier"),
                           ("Cancel", "hotkeys.cancel")):
            edit = ShortcutEdit(self.svc.pause_hotkeys)
            edit.changed.connect(lambda _=None: self._check_conflicts())
            self.shortcut_edits[key] = edit
            form.addRow(label, self.bind(edit, key))
        lay.addLayout(form)
        self.conflict = QLabel("")
        self.conflict.setStyleSheet(f"color: {theme.DANGER};")
        lay.addWidget(self.conflict)
        form2 = QFormLayout()
        form2.addRow("Allow push to talk", self.bind(QCheckBox(), "activation.push_to_talk"))
        form2.addRow("Allow toggle", self.bind(QCheckBox(), "activation.toggle"))
        form2.addRow("Allow always listening", self.bind(QCheckBox(), "activation.always_listening_allowed"))
        lay.addLayout(form2)
        lay.addStretch(1)
        return w

    def _check_conflicts(self) -> None:
        seen: dict[str, str] = {}
        problems = []
        for key in ("hotkeys.push_to_talk", "hotkeys.toggle", "hotkeys.always_listening"):
            spec = self.shortcut_edits[key].text()
            try:
                Chord.parse(spec)
            except ValueError as exc:
                problems.append(f"{spec or 'empty'}: {exc}")
                continue
            if spec in seen:
                problems.append(f"{spec} is used twice")
            seen[spec] = key
        self.conflict.setText("; ".join(problems))

    def _page_mic(self) -> QWidget:
        w, lay = self._page("Microphone")
        form = QFormLayout()
        self.device = self._combo([("System default", "")])
        for dev_id, name in self.svc.devices():
            self.device.addItem(name, dev_id)
        form.addRow("Input device", self.bind(self.device, "audio.device"))
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        form.addRow("Level", self.level)
        self.vad = QSlider(Qt.Orientation.Horizontal)
        self.vad.setRange(-70, -20)
        self.vad_label = QLabel("")
        self.vad.valueChanged.connect(lambda v: self.vad_label.setText(f"{v} dB"))
        row = QHBoxLayout()
        row.addWidget(self.vad, 1)
        row.addWidget(self.vad_label)
        form.addRow("Speech threshold", self.bind(self.vad, "audio.vad_threshold_db") and row)
        self.calibrate_btn = QPushButton("Calibrate (2 s of silence)")
        self.calibrate_btn.setEnabled(self.svc.calibrate is not None)
        self.calibrate_btn.clicked.connect(self._calibrate)
        form.addRow("", self.calibrate_btn)
        form.addRow("Pause that ends a phrase (ms, always listening)", self.bind(self._spin(200, 3000), "audio.end_of_speech_ms"))
        lay.addLayout(form)
        lay.addStretch(1)
        return w

    @staticmethod
    def _spin(lo: int, hi: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        return s

    def set_level(self, level: float) -> None:
        self.level.setValue(int(max(0.0, min(1.0, level)) * 100))

    def _calibrate(self) -> None:
        self.calibrate_btn.setEnabled(False)
        self.calibrate_btn.setText("Listening…")

        def work() -> None:
            self._calibrated.emit(self.svc.calibrate() if self.svc.calibrate else None)

        threading.Thread(target=work, daemon=True).start()

    def _apply_calibration(self, floor_db: float | None) -> None:
        self.calibrate_btn.setEnabled(True)
        self.calibrate_btn.setText("Calibrate (2 s of silence)")
        if floor_db is not None:
            self.vad.setValue(int(max(-70, min(-20, floor_db + 12))))

    def _page_stt(self) -> QWidget:
        w, lay = self._page("Speech engine", "Sayso tries engines from the top. Uncheck one to skip it.")
        self.stt_order = _OrderedList({"faster_whisper": "Faster Whisper (local)", "whisper_cpp": "whisper.cpp (local)",
                                       "windows_speech": "Windows Speech (built in)", "cloud": "Cloud transcription"})
        self.stt_order.set_items(self.loaded.settings.stt.engines, STT_ENGINES)
        lay.addWidget(self.stt_order)
        for name, status in self.svc.stt_status():
            self.stt_order.set_status(name, status)
        form = QFormLayout()
        form.addRow("Language", self.bind(self._combo([("English", "en"), ("Automatic", ""), ("Spanish", "es"), ("French", "fr"),
                                                       ("German", "de"), ("Portuguese", "pt"), ("Hindi", "hi")], editable=False),
                                           "stt.language"))
        form.addRow("Faster Whisper model", self.bind(self._combo(FW_MODELS, editable=True), "stt.faster_whisper.model"))
        row = QHBoxLayout()
        self.dl_btn = QPushButton("Download model")
        self.dl_btn.setEnabled(self.svc.download_model is not None and not self.loaded.settings.privacy.offline_only)
        self.dl_btn.clicked.connect(self._download)
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        row.addWidget(self.dl_btn)
        row.addWidget(self.dl_bar, 1)
        form.addRow("", row)
        form.addRow("whisper.cpp program", self.bind(QLineEdit(), "stt.whisper_cpp.cli_path"))
        form.addRow("whisper.cpp model", self.bind(QLineEdit(), "stt.whisper_cpp.model_path"))
        form.addRow("Windows Speech language", self.bind(QLineEdit(), "stt.windows_speech.culture"))
        form.addRow("Cloud transcription URL", self.bind(QLineEdit(), "stt.cloud.base_url"))
        self.stt_key = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self._key_field(self.stt_key, self.loaded.settings.stt.cloud.api_key_ref)
        form.addRow("Cloud transcription key", self.stt_key)
        lay.addLayout(form)
        return w

    def _download(self) -> None:
        self.dl_btn.setEnabled(False)
        model = self.bind_value("stt.faster_whisper.model")

        def work() -> None:
            try:
                self._downloaded.emit(self.svc.download_model(model, self._progress.emit))  # type: ignore[misc]
            except Exception as exc:
                self._downloaded.emit(f"Failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _download_done(self, message: str) -> None:
        self.dl_btn.setEnabled(True)
        self.dl_btn.setText(message[:40] or "Download model")

    def bind_value(self, dotted: str) -> Any:
        for d, get, _, _ in self._bindings:
            if d == dotted:
                return get()
        return _get(self._data, dotted)

    def _key_field(self, field_: QLineEdit, ref: str) -> None:
        field_.setPlaceholderText("Saved" if ref and self.svc.secret_present(ref) else "Not set")
        field_.textEdited.connect(lambda text, r=ref: self._pending_keys.__setitem__(r, text) if text else None)
        if self.loaded.is_locked("llm.providers") or not ref:
            field_.setEnabled(bool(ref))

    def _page_ai(self) -> QWidget:
        w, lay = self._page("AI", "Sayso asks the checked providers in order. The built-in offline writer is always the last resort.")
        row = QHBoxLayout()
        self.chain_list = _OrderedList()
        self.chain_list.setMinimumWidth(190)
        self.chain_list.set_items(self.loaded.settings.llm.chain, list(self._providers))
        self.chain_list.list.currentItemChanged.connect(lambda cur, prev: self._select_provider(cur))
        row.addWidget(self.chain_list, 1)
        form = QFormLayout()
        self.p_kind = self._combo(PROVIDER_KINDS)
        self.p_url, self.p_model = QLineEdit(), QLineEdit()
        self.p_deployment, self.p_version, self.p_effort = QLineEdit(), QLineEdit(), QLineEdit()
        self.p_key = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        for label, widget in (("Type", self.p_kind), ("Address", self.p_url), ("Model", self.p_model),
                              ("Azure deployment", self.p_deployment), ("Azure API version", self.p_version),
                              ("Claude effort", self.p_effort), ("API key", self.p_key)):
            form.addRow(label, widget)
        self.p_key.textEdited.connect(self._provider_key_edited)
        self.test_btn = QPushButton("Test")
        self.test_btn.setEnabled(self.svc.test_provider is not None)
        self.test_btn.clicked.connect(self._test)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        form.addRow(self.test_btn, self.test_result)
        form.addRow("Give up after (seconds)", self.bind(self._spin(1, 60), "llm.timeout_s"))
        row.addLayout(form, 2)
        lay.addLayout(row, 1)
        if self.chain_list.list.count():
            self.chain_list.list.setCurrentRow(0)
        if self.loaded.is_locked("llm.providers"):
            for wdg in (self.p_kind, self.p_url, self.p_model, self.p_deployment, self.p_version, self.p_effort):
                wdg.setEnabled(False)
                wdg.setToolTip(LOCKED_TIP)
        return w

    def _select_provider(self, item: QListWidgetItem | None) -> None:
        self._store_provider()
        if item is None:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self._current_provider = name
        p = self._providers[name]
        self.p_kind.setCurrentIndex(max(0, self.p_kind.findText(p.kind)))
        for widget, value in ((self.p_url, p.base_url), (self.p_model, p.model), (self.p_deployment, p.deployment),
                              (self.p_version, p.api_version), (self.p_effort, p.effort)):
            widget.setText(value)
        self.p_key.clear()
        self.p_key.setPlaceholderText("Saved" if p.api_key_ref and self.svc.secret_present(p.api_key_ref) else
                                      "Not needed" if not p.api_key_ref else "Not set")
        self.p_key.setEnabled(bool(p.api_key_ref))
        self.test_result.setText("")

    def _store_provider(self) -> None:
        name = self._current_provider
        if name and name in self._providers:
            p = self._providers[name]
            p.kind, p.base_url, p.model = self.p_kind.currentText(), self.p_url.text().strip(), self.p_model.text().strip()
            p.deployment, p.api_version, p.effort = (self.p_deployment.text().strip(), self.p_version.text().strip(),
                                                    self.p_effort.text().strip())

    def _provider_key_edited(self, text: str) -> None:
        ref = self._providers[self._current_provider].api_key_ref if self._current_provider else ""
        if ref and text:
            self._pending_keys[ref] = text

    def _test(self) -> None:
        self._store_provider()
        name = self._current_provider
        if not name or self.svc.test_provider is None:
            return
        p = copy.deepcopy(self._providers[name])
        key = self.p_key.text() or None
        self.test_btn.setEnabled(False)
        self.test_result.setText("Testing…")

        def work() -> None:
            try:
                ok, ms, text = self.svc.test_provider(name, p, key)  # type: ignore[misc]
            except Exception as exc:
                ok, ms, text = False, 0, str(exc)
            self._tested.emit(ok, ms, text)

        threading.Thread(target=work, daemon=True).start()

    def _show_test(self, ok: bool, ms: int, text: str) -> None:
        self.test_btn.setEnabled(True)
        color = theme.SUCCESS if ok else theme.DANGER
        self.test_result.setStyleSheet(f"color: {color};")
        self.test_result.setText(f"Worked in {ms / 1000:.1f} s: {text}" if ok else f"Did not work: {text}")

    def _page_apps(self) -> QWidget:
        w, lay = self._page("Apps", "Choose how Sayso writes in each program. Use the program's name as it appears in Task "
                                  "Manager, without .exe.")
        self.profiles = QTableWidget(0, 3)
        self.profiles.setHorizontalHeaderLabels(["Programs (comma separated)", "Style", "Tone note"])
        self.profiles.horizontalHeader().setStretchLastSection(True)
        self.profiles.setColumnWidth(0, 200)
        self.profiles.setColumnWidth(1, 140)
        self.profiles.verticalHeader().hide()
        for p in self.loaded.settings.profiles:
            self._add_profile(p)
        btns = QHBoxLayout()
        for label, fn in (("Add", lambda: self._add_profile(AppProfile())), ("Use current app", self._add_current_app),
                          ("Remove", self._remove_profile)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addWidget(self.profiles, 1)
        lay.addLayout(btns)
        lay.addWidget(QLabel("How text is inserted"))
        form = QFormLayout()
        form.addRow("Default method", self.bind(self._combo(INJECTION_METHODS), "injection.method"))
        lay.addLayout(form)
        self.overrides = _KeyValueTable(("Program", "Method (paste, clipboard, accessibility, keyboard)"))
        self.overrides.load(self.loaded.settings.injection.app_overrides)
        self.overrides.setMaximumHeight(130)
        lay.addWidget(self.overrides)
        ob = QHBoxLayout()
        add, rem = QPushButton("Add override"), QPushButton("Remove override")
        add.clicked.connect(lambda: self.overrides.add_row())
        rem.clicked.connect(self.overrides.remove_selected)
        ob.addWidget(add)
        ob.addWidget(rem)
        ob.addStretch(1)
        lay.addLayout(ob)
        return w

    def _add_profile(self, p: AppProfile) -> None:
        r = self.profiles.rowCount()
        self.profiles.insertRow(r)
        self.profiles.setItem(r, 0, QTableWidgetItem(", ".join(p.processes)))
        combo = self._combo([("Default", ""), *[(m.label, m.value) for m in USER_MODES]])
        combo.setCurrentIndex(max(0, combo.findData(p.mode.value if p.mode else "")))
        self.profiles.setCellWidget(r, 1, combo)
        self.profiles.setItem(r, 2, QTableWidgetItem(p.tone))

    def _add_current_app(self) -> None:
        proc = self.svc.last_foreground_process()
        if proc:
            self._add_profile(AppProfile([proc]))

    def _remove_profile(self) -> None:
        for r in sorted({i.row() for i in self.profiles.selectedIndexes()}, reverse=True):
            self.profiles.removeRow(r)

    def _dump_profiles(self) -> list[dict[str, Any]]:
        out = []
        for r in range(self.profiles.rowCount()):
            procs = [p.strip() for p in (self.profiles.item(r, 0).text() if self.profiles.item(r, 0) else "").split(",") if p.strip()]
            if not procs:
                continue
            mode = self.profiles.cellWidget(r, 1).currentData() or None
            out.append({"processes": procs, "mode": mode, "tone": self.profiles.item(r, 2).text() if self.profiles.item(r, 2) else ""})
        return out

    def _page_words(self) -> QWidget:
        w, lay = self._page("Words", "Fix words Sayso mishears, and say a short phrase to insert longer text.")
        self.vocab = _KeyValueTable(("When it hears", "Write"))
        self.vocab.load(self.loaded.settings.vocabulary)
        self.snippets = _KeyValueTable(("When you say", "Insert"))
        self.snippets.load(self.loaded.settings.snippets)
        for title, table in (("Vocabulary", self.vocab), ("Snippets", self.snippets)):
            lay.addWidget(QLabel(title))
            lay.addWidget(table, 1)
            row = QHBoxLayout()
            add, rem = QPushButton("Add"), QPushButton("Remove")
            add.clicked.connect(lambda _=False, t=table: t.add_row())
            rem.clicked.connect(table.remove_selected)
            row.addWidget(add)
            row.addWidget(rem)
            row.addStretch(1)
            lay.addLayout(row)
        return w

    def _page_privacy(self) -> QWidget:
        w, lay = self._page("Privacy")
        form = QFormLayout()
        form.addRow("Keep a history of dictations", self.bind(QCheckBox(), "privacy.history_enabled"))
        form.addRow("Keep history for (days, 0 = forever)", self.bind(self._spin(0, 3650), "privacy.history_retention_days"))
        form.addRow("Send app name and nearby text to the AI", self.bind(QCheckBox(), "privacy.share_context"))
        form.addRow("Offline only (never use the internet)", self.bind(QCheckBox(), "privacy.offline_only"))
        tele = QCheckBox("Sayso never sends usage data")
        tele.setChecked(False)
        tele.setEnabled(False)
        form.addRow("Telemetry", tele)
        lay.addLayout(form)
        self.blocked = QPlainTextEdit("\n".join(self.loaded.settings.privacy.blocked_apps))
        self.no_cloud = QPlainTextEdit("\n".join(self.loaded.settings.privacy.no_cloud_apps))
        for label, edit, key in (("Never listen in these programs (one per line)", self.blocked, "privacy.blocked_apps"),
                                 ("Never use cloud AI in these programs", self.no_cloud, "privacy.no_cloud_apps")):
            lay.addWidget(QLabel(label))
            edit.setMaximumHeight(70)
            if self.loaded.is_locked(key):
                edit.setEnabled(False)
                edit.setToolTip(LOCKED_TIP)
            lay.addWidget(edit)
        delete = QPushButton("Delete history now")
        theme.set_prop(delete, "danger")
        delete.clicked.connect(self.svc.delete_history)
        lay.addWidget(delete)
        lay.addStretch(1)
        return w

    def _page_diag(self) -> QWidget:
        w, lay = self._page("Diagnostics", "What this computer allows Sayso to do.")
        self.diag = QListWidget()
        lay.addWidget(self.diag, 1)
        row = QHBoxLayout()
        run, copy_btn = QPushButton("Run checks"), QPushButton("Copy report")
        run.clicked.connect(self.run_diagnostics)
        copy_btn.clicked.connect(self._copy_report)
        row.addWidget(run)
        row.addWidget(copy_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._report: dict[str, Any] = {}
        return w

    def run_diagnostics(self) -> None:
        self._report = self.svc.diagnostics()
        self.diag.clear()
        for key, val in self._report.items():
            if isinstance(val, list) and len(val) == 2:
                status, detail = val
                mark = {"ok": "✓", "blocked": "✕", "missing": "✕"}.get(status, "?")
                text = f"{mark}  {key.replace('_', ' ')}: {status}" + (f" ({detail})" if detail else "")
                hint = self.svc.fix_hints.get(key) if status in {"blocked", "missing"} else None
                if hint:
                    text += f"\n     {hint}"
            elif isinstance(val, dict):
                text = f"{key.replace('_', ' ')}: " + ", ".join(f"{n} {s[0]}" for n, s in val.items())
            else:
                text = f"{key.replace('_', ' ')}: {val}"
            self.diag.addItem(text)

    def _copy_report(self) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(json.dumps(self._report, indent=2))


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


