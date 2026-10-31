"""Wires hotkeys, microphone, speech, AI, insertion and the overlay into the dictation flow."""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from sayso.audio.capture import AudioCapture, MicrophoneUnavailable
from sayso.audio.vad import EnergyVad, VadEventKind, frame_db
from sayso.core import capabilities
from sayso.core.config import LoadedSettings, ProviderSettings, Settings, load_settings, save_settings
from sayso.core.context import FocusContext
from sayso.core.history import History
from sayso.core.modes import Mode
from sayso.core.paths import AppPaths, app_dir
from sayso.core.pipeline import DictationResult, Pipeline, Stage, join_with_context
from sayso.core.telemetry import LatencySample, LocalMetrics
from sayso.llm.prompts import PromptContext
from sayso.llm.registry import ProviderChain
from sayso.stt.base import AudioClip
from sayso.stt.registry import NoEngineAvailable, SttChain
from sayso.ui import icons
from sayso.ui.history_window import HistoryWindow
from sayso.ui.overlay import Overlay, OverlayState
from sayso.ui.settings_window import SettingsServices, SettingsWindow
from sayso.ui.tray import Tray
from sayso.winsys.credentials import CredentialStore
from sayso.winsys.injection import Injector

log = logging.getLogger(__name__)

SETTINGS_DEBOUNCE_MS = 300
CONTEXT_WAIT_S = 0.3

FIX_HINTS = {
    "microphone": "Turn on Settings > Privacy > Microphone > Let desktop apps access your microphone.",
    "clipboard": "Sayso will use accessibility or typing instead of paste.",
    "keyboard_hook": "Push-to-talk needs the keyboard hook. Use the toggle shortcut or the tray menu.",
    "powershell": "Windows Speech needs PowerShell; the local Faster Whisper engine does not.",
    "internet": "Cloud AI is unreachable. Sayso uses local models or its offline writer.",
}


def describe_error(exc: BaseException) -> str:
    """Plain-language message for the overlay. Never includes dictated text."""
    from sayso.winsys.clipboard import ClipboardBusy

    if isinstance(exc, MicrophoneUnavailable):
        return str(exc)
    if isinstance(exc, NoEngineAvailable):
        return "No speech engine could run. Open Settings > Diagnostics."
    if isinstance(exc, ClipboardBusy):
        return "The clipboard is locked by another program."
    return f"Something went wrong ({type(exc).__name__}). See the log."


@dataclass
class JobOutcome:
    result: DictationResult | None = None
    insert_method: str = ""
    insert_ok: bool = True
    manual_paste: bool = False
    insert_ms: int = 0
    elevated: bool = False
    error: str = ""
    cancelled: bool = False
    app: str = ""


class Controller(QObject):
    dictated = Signal(object)
    _outcome = Signal(object)
    _stage = Signal(str)
    _transcript = Signal(str, object)
    _delta = Signal(str)
    _level = Signal(float)
    _segment = Signal(object, object)
    _warm = Signal(str)
    _notify = Signal(str, str, bool)

    def __init__(self, app: QApplication, paths: AppPaths, loaded: LoadedSettings, creds: CredentialStore,
                 history: History, *, hotkeys=None, audio: AudioCapture | None = None, injector=None,
                 capture_context: Callable[[int], FocusContext] | None = None,
                 foreground: Callable[[], int] | None = None, tray: Tray | None = None, enable_tray: bool = True):
        super().__init__()
        self.app, self.paths, self.loaded, self.creds, self.history = app, paths, loaded, creds, history
        self.metrics = LocalMetrics()
        self._ctx_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sayso-ctx")
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sayso-work")
        self._recording = False
        self._kind = "toggle"
        self._command = False
        self._paused = False
        self._mode_override: Mode | None = None
        self._inflight: list[threading.Event] = []
        self._target_hwnd = 0
        self._ctx_future: Future | None = None
        self._always_on = False
        self._vad: EnergyVad | None = None
        self._vad_ctx: Future | None = None
        self._vad_hwnd = 0
        self._last_foreground_process = ""
        self._warning_shown = False

        self._hotkeys = hotkeys
        self._audio_override, self._injector_override = audio, injector
        self._capture_context, self._foreground = capture_context, foreground
        self.audio: AudioCapture = audio or self._new_audio()
        self.overlay = Overlay()
        self.tray: Tray | None = tray
        self._enable_tray = enable_tray
        self.history_window: HistoryWindow | None = None
        self.settings_window: SettingsWindow | None = None
        self._watcher = QFileSystemWatcher(self)
        self._debounce = QTimer(self, singleShot=True, interval=SETTINGS_DEBOUNCE_MS)
        self._debounce.timeout.connect(self.reload_settings)
        self._sounds: dict[str, object] = {}

        self._outcome.connect(self._on_outcome)
        self._stage.connect(self._on_stage)
        self._transcript.connect(self._on_transcript)
        self._delta.connect(self.overlay.append_preview)
        self._level.connect(self._on_level)
        self._segment.connect(self._on_segment)
        self._warm.connect(self._on_warm)
        self._notify.connect(lambda t, m, e: self.tray and self.tray.notify(t, m, e))
        self._build_services()

    # -- construction

    @property
    def settings(self) -> Settings:
        return self.loaded.settings

    def _new_audio(self) -> AudioCapture:
        a = self.settings.audio
        cap = AudioCapture(a.sample_rate, a.device, max_seconds=a.max_seconds)
        cap.on_level = self._level.emit
        return cap

    def _build_services(self) -> None:
        s = self.settings
        app_root = app_dir()
        offline = s.privacy.offline_only
        self.stt = SttChain.from_settings(s.stt, models_dir=self.paths.models_dir, app_dir=app_root,
                                          secrets=self.creds.get, offline_only=offline)
        self.llm = ProviderChain(s.llm, self.creds.get, offline_only=offline)
        self.pipeline = Pipeline(self.stt, self.llm, lambda: self.settings)
        self.injector = self._injector_override or Injector(s.injection)
        if self._injector_override is None:
            self.injector.settings = s.injection
        self.history.enabled = s.privacy.history_enabled
        self.history.retention_days = s.privacy.history_retention_days
        self.overlay.configure(s.general.overlay_position)

    # -- lifecycle

    def start(self) -> None:
        from sayso.winsys import context

        context.set_comtypes_gen_dir(self.paths.data_dir / "comtypes_gen")
        if self._capture_context is None:
            self._capture_context = context.capture
        if self._foreground is None:
            self._foreground = context.foreground_hwnd
        if self._hotkeys is None:
            from sayso.winsys.hotkeys import HotkeyService

            self._hotkeys = HotkeyService(self.settings.hotkeys, self.settings.activation)
        h = self._hotkeys
        h.started.connect(self._on_hotkey_start)
        h.stopped.connect(self.stop_dictation)
        h.cancelled.connect(self.cancel)
        h.command_engaged.connect(self._engage_command)
        h.always_listening_toggled.connect(lambda: self.set_always_listening(not self._always_on))
        h.backend_changed.connect(self._on_backend)

        if self._enable_tray and self.tray is None:
            self.tray = Tray(show_always_listening=self.settings.activation.always_listening_allowed,
                             offline_locked=self.loaded.is_locked("privacy.offline_only"),
                             managed=self.loaded.policy_present)
        if self.tray:
            self._wire_tray()
            self.tray.set_tooltip(self._tooltip())
            self.tray.show()
        for f in (self.paths.settings_file, self.paths.policy_file):
            if f.exists():
                self._watcher.addPath(str(f))
        self._watcher.fileChanged.connect(self._on_file_changed)
        h.start()
        self._load_sounds()
        threading.Thread(target=self._warm_up, name="sayso-warmup", daemon=True).start()
        if not self.paths.settings_file.exists():
            QTimer.singleShot(400, self._first_run)

    def shutdown(self) -> None:
        self.cancel()
        if self._hotkeys:
            self._hotkeys.stop()
        self.audio.close()
        self._worker.shutdown(wait=False, cancel_futures=True)
        self._ctx_pool.shutdown(wait=False, cancel_futures=True)
        self.stt.close()
        self.llm.close()
        if self.tray:
            self.tray.hide()
        self.history.close()

    def _wire_tray(self) -> None:
        t = self.tray
        assert t is not None
        t.toggle_dictation.connect(self._tray_toggle)
        t.mode_chosen.connect(lambda m: setattr(self, "_mode_override", m))
        t.always_listening.connect(self.set_always_listening)
        t.pause_toggled.connect(self._set_paused)
        t.offline_toggled.connect(self._set_offline)
        t.open_history.connect(self.show_history)
        t.open_settings.connect(self.show_settings)
        t.open_diagnostics.connect(lambda: self.show_settings(page="Diagnostics"))
        t.open_logs.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.log_file.parent))))
        t.quit_requested.connect(self.app.quit)
        t.offline_action.setChecked(self.settings.privacy.offline_only)

    def _tooltip(self) -> str:
        hk = self.settings.hotkeys
        return f"Sayso · hold {hk.push_to_talk} to dictate"

    def _load_sounds(self) -> None:
        if not self.settings.general.sounds:
            return
        try:
            from PySide6.QtCore import QUrl as U
            from PySide6.QtMultimedia import QSoundEffect

            for name in ("start", "stop", "error"):
                f = icons.asset_dir() / "sounds" / f"{name}.wav"
                if f.exists():
                    fx = QSoundEffect(self)
                    fx.setSource(U.fromLocalFile(str(f)))
                    fx.setVolume(0.5)
                    self._sounds[name] = fx
        except Exception:
            log.debug("sound effects unavailable", exc_info=True)

    def _play(self, name: str) -> None:
        fx = self._sounds.get(name)
        if fx is not None and self.settings.general.sounds:
            fx.play()  # type: ignore[attr-defined]

    # -- hotkey / tray entry points

    def _on_hotkey_start(self, kind: str, command: bool) -> None:
        self.start_dictation(kind, command)

    def _tray_toggle(self) -> None:
        if self._recording:
            self.stop_dictation()
        else:
            self.start_dictation("toggle", False)

    def _set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused and self._recording:
            self.cancel()
        if self.tray:
            self.tray.set_state(paused=paused, offline=self.settings.privacy.offline_only)

    def _set_offline(self, on: bool) -> None:
        if self.loaded.is_locked("privacy.offline_only"):
            return
        s = dataclasses.replace(self.settings, privacy=dataclasses.replace(self.settings.privacy, offline_only=on))
        self._save_and_apply(s)

    def _engage_command(self) -> None:
        if self._recording and not self._command:
            self._command = True
            self.overlay.set_state(OverlayState.COMMAND)

    def _on_backend(self, name: str) -> None:
        if name == "registerhotkey":
            self._notify.emit("Sayso", "Push-to-talk unavailable on this PC. Press Ctrl+Alt+Space to start and again to stop.", True)
        elif name == "none":
            self._notify.emit("Sayso", "Use the tray icon to dictate.", True)

    # -- dictation

    @property
    def busy(self) -> bool:
        return bool(self._inflight)

    def start_dictation(self, kind: str = "toggle", command: bool = False) -> None:
        if self._paused or self._recording or self.busy:
            return
        self._pause_vad(True)
        self._target_hwnd = self._foreground() if self._foreground else 0
        self._ctx_future = self._ctx_pool.submit(self._safe_capture, self._target_hwnd)
        try:
            self.audio.start()
        except MicrophoneUnavailable as exc:
            self._fail(str(exc))
            return
        self._recording, self._kind, self._command = True, kind, command
        state = OverlayState.COMMAND if command else OverlayState.RECORDING if kind == "ptt" else OverlayState.HANDS_FREE
        self.overlay.set_mode("")
        if self.settings.general.show_overlay:
            self.overlay.set_state(state)
        self._play("start")
        if self.tray:
            self.tray.set_state(recording=True)

    def stop_dictation(self) -> None:
        if not self._recording:
            return
        self._recording = False
        clip = self.audio.stop()
        if not self._always_on:
            self.audio.close()
        self._play("stop")
        if self.tray:
            self.tray.set_state(paused=self._paused, offline=self.settings.privacy.offline_only)
        self._pause_vad(False)
        self._submit(clip, self._ctx_future, self._target_hwnd, self._command)

    def cancel(self) -> None:
        was_recording = self._recording
        if was_recording:
            self._recording = False
            self.audio.cancel()
            if not self._always_on:
                self.audio.close()
            self._pause_vad(False)
        for ev in self._inflight:
            ev.set()
        if was_recording or self._inflight:
            self.overlay.set_state(OverlayState.HIDDEN)
        if self._hotkeys:
            self._hotkeys.force_idle()
            self._hotkeys.set_processing(False)
        self._inflight.clear()
        if self.tray:
            self.tray.set_state(paused=self._paused, offline=self.settings.privacy.offline_only)

    def _safe_capture(self, hwnd: int) -> FocusContext:
        try:
            assert self._capture_context is not None
            ctx = self._capture_context(hwnd)
            self._last_foreground_process = ctx.process or self._last_foreground_process
            return ctx
        except Exception:
            log.debug("context capture failed", exc_info=True)
            return FocusContext(hwnd=hwnd)

    def _submit(self, clip: AudioClip, ctx_future: Future | None, hwnd: int, command: bool) -> None:
        cancel = threading.Event()
        self._inflight.append(cancel)
        if self.settings.general.show_overlay:
            self.overlay.set_state(OverlayState.PROCESSING)
        if self._hotkeys:
            self._hotkeys.set_processing(True)
        mode_override = self._mode_override
        self._worker.submit(self._job, clip, ctx_future, hwnd, command, mode_override, cancel)

    def _job(self, clip: AudioClip, ctx_future: Future | None, hwnd: int, command: bool, mode_override: Mode | None,
             cancel: threading.Event) -> None:
        out = JobOutcome()
        try:
            ctx = FocusContext(hwnd=hwnd)
            if ctx_future is not None:
                try:
                    ctx = ctx_future.result(timeout=CONTEXT_WAIT_S)
                except Exception:
                    log.debug("context not ready; continuing with basics")
            out.app = ctx.process
            if command and not ctx.selection:
                sel = self.injector.copy_selection()
                if sel:
                    ctx = dataclasses.replace(ctx, selection=sel)
            if cancel.is_set():
                raise _Cancelled
            result = self.pipeline.run(
                clip, ctx, mode_override=mode_override, command=command,
                on_stage=lambda st: self._stage.emit(st.value),
                on_transcript=lambda t, c: self._transcript.emit(t, c),
                on_delta=lambda d: self._delta.emit(d))
            out.result = result
            if cancel.is_set():
                raise _Cancelled
            if not result.text:
                self._outcome.emit(out)
                return
            text = join_with_context(result.text, ctx, result.replace_selection)
            report = self.injector.insert(text, ctx, replace_selection=result.replace_selection)
            out.insert_method, out.insert_ok, out.manual_paste = report.method, report.ok, report.needs_manual_paste
            out.insert_ms, out.elevated = report.ms, ctx.is_elevated_target
            self.history.add(app=ctx.process, mode=result.mode.value, transcript=result.transcript, text=result.text,
                             stt_engine=result.stt_engine, llm_provider=result.llm_provider,
                             latency_ms=result.timings.after_release_ms + report.ms, confidence=result.confidence)
            self.metrics.add(LatencySample(int(result.timings.stt_s * 1000), int(result.timings.llm_s * 1000), report.ms))
            log.info("inserted via %s in %d ms (tried %s)", report.method, report.ms, [t[0] for t in report.tried])
        except _Cancelled:
            out.cancelled = True
        except Exception as exc:
            log.exception("dictation failed")
            out.error = describe_error(exc)
        self._outcome.emit(out)

    # -- UI-thread callbacks

    def _on_stage(self, stage: str) -> None:
        if stage == Stage.REWRITING.value:
            self.overlay.set_state(OverlayState.PROCESSING)

    def _on_transcript(self, text: str, confidence) -> None:
        self.overlay.set_preview(text)
        self.overlay.set_confidence(confidence)

    def _on_level(self, level: float) -> None:
        self.overlay.set_level(level)
        if self.settings_window is not None and self.settings_window.isVisible():
            self.settings_window.set_level(level)

    def _on_outcome(self, out: JobOutcome) -> None:
        if self._inflight:
            self._inflight.pop(0)
        if not self._inflight and self._hotkeys:
            self._hotkeys.set_processing(False)
        if out.cancelled:
            if not self._inflight and not self._recording:
                self.overlay.set_state(OverlayState.HIDDEN)
            return
        if not self.settings.general.show_overlay and not out.error:
            return
        r = out.result
        if out.error:
            self._play("error")
            self.overlay.set_state(OverlayState.ERROR, out.error)
        elif r is None or not r.text:
            reason = r.skipped_reason if r else ""
            if reason in {"no speech", "nothing recognised"}:
                self.overlay.set_state(OverlayState.ERROR, "Didn't catch that.")
            elif reason:
                self.overlay.set_state(OverlayState.ERROR, f"Not dictating here ({reason}).")
            else:
                self.overlay.set_state(OverlayState.HIDDEN)
        else:
            total = r.timings.after_release_ms + out.insert_ms
            self.overlay.set_mode(r.mode.label)
            self.overlay.set_latency(total)
            self.overlay.set_confidence(r.confidence)
            if not out.insert_ok:
                self._play("error")
                self.overlay.set_state(OverlayState.ERROR, "Couldn't insert the text. It is saved in History.")
            elif out.manual_paste:
                msg = ("Can't type into an admin window. Copied. Press Ctrl+V." if out.elevated
                       else "Copied. Press Ctrl+V")
                self.overlay.set_state(OverlayState.SUCCESS, msg)
            else:
                self.overlay.set_state(OverlayState.SUCCESS, f"Inserted · {total / 1000:.1f} s")
            self.dictated.emit(r)
            if self.history_window is not None and self.history_window.isVisible():
                self.history_window.refresh()
        if self._always_on and not self._inflight and not self._recording and (out.result is None or not out.result.text):
            QTimer.singleShot(1200, self._restore_listening_pill)

    def _restore_listening_pill(self) -> None:
        if self._always_on and not self.busy and not self._recording:
            self.overlay.set_state(OverlayState.ALWAYS_LISTENING)

    def _fail(self, message: str) -> None:
        self._recording = False
        self._pause_vad(False)
        if self._hotkeys:
            self._hotkeys.force_idle()
        self._play("error")
        self.overlay.set_state(OverlayState.ERROR, message)

    # -- always listening

    def set_always_listening(self, on: bool) -> None:
        if on == self._always_on:
            return
        if on and not self.settings.activation.always_listening_allowed:
            return
        self._always_on = on
        a = self.settings.audio
        if on:
            self._vad = EnergyVad(a.sample_rate, 30, a.vad_threshold_db, end_ms=a.end_of_speech_ms)
            self.audio.on_frame = self._on_frame
            try:
                self.audio.open()
            except MicrophoneUnavailable as exc:
                self._always_on = False
                self.audio.on_frame = None
                self._fail(str(exc))
                return
            self.audio.start()
            self.overlay.set_state(OverlayState.ALWAYS_LISTENING)
        else:
            self.audio.on_frame = None
            self.audio.cancel()
            if not self._recording:
                self.audio.close()
            self.overlay.set_state(OverlayState.HIDDEN)
        if self.tray:
            self.tray.always_action.blockSignals(True)
            self.tray.always_action.setChecked(on)
            self.tray.always_action.blockSignals(False)

    def _pause_vad(self, paused: bool) -> None:
        if self._vad is not None:
            self._vad_paused = paused
            if paused:
                self._vad.reset()

    _vad_paused = False

    def _on_frame(self, frame) -> None:  # audio thread
        vad = self._vad
        if vad is None or self._vad_paused or self._recording:
            return
        for ev in vad.process(frame):
            if ev.kind is VadEventKind.SPEECH_START:
                hwnd = self._foreground() if self._foreground else 0
                self._vad_hwnd = hwnd
                self._vad_ctx = self._ctx_pool.submit(self._safe_capture, hwnd)
            elif ev.segment is not None:
                clip = AudioClip(ev.segment, self.settings.audio.sample_rate)
                self._segment.emit(clip, (self._vad_ctx, self._vad_hwnd))

    def _on_segment(self, clip: AudioClip, ctx_info) -> None:
        if self._paused or self._recording:
            return
        fut, hwnd = ctx_info
        self._submit(clip, fut, hwnd, False)

    # -- settings

    def _on_file_changed(self, path: str) -> None:
        self._debounce.start()
        from pathlib import Path

        if Path(path).exists() and path not in self._watcher.files():
            self._watcher.addPath(path)

    def reload_settings(self) -> None:
        self.loaded = load_settings(self.paths.settings_file, self.paths.policy_file if self.paths.policy_file.exists() else None)
        self._apply_loaded()

    def _apply_loaded(self) -> None:
        old_stt, old_llm = self.stt, self.llm
        self._build_services()
        old_stt.close()
        old_llm.close()
        if self._audio_override is None:
            self.audio.close()
            self.audio = self._new_audio()
        if self._hotkeys:
            self._hotkeys.reconfigure(self.settings.hotkeys, self.settings.activation)
        threading.Thread(target=self._warm_up, name="sayso-warmup", daemon=True).start()
        if self.tray:
            self.tray.set_tooltip(self._tooltip())
            self.tray.offline_action.blockSignals(True)
            self.tray.offline_action.setChecked(self.settings.privacy.offline_only)
            self.tray.offline_action.blockSignals(False)
            self.tray.set_state(paused=self._paused, offline=self.settings.privacy.offline_only)

    def _save_and_apply(self, new: Settings) -> None:
        save_settings(new, self.paths.settings_file, self.loaded.locked)
        self.reload_settings()

    def _first_run(self) -> None:
        w = self.show_settings(page="AI")
        hk = self.settings.hotkeys
        w.show_welcome(f"Welcome to Sayso. Hold {hk.push_to_talk} and speak; let go and the text appears where you are typing. "
                       f"Double-tap {hk.toggle.split('*')[0]} or press {hk.toggle} to dictate hands-free. Add an AI key below, "
                       "or leave it: Sayso still cleans up your words offline.")

    def show_history(self) -> None:
        if self.history_window is None:
            self.history_window = HistoryWindow(self.history, lambda: self.settings.privacy.history_retention_days)
            self.history_window.insert_again.connect(self._insert_again)
        self.history_window.refresh()
        self.history_window.show()
        self.history_window.raise_()
        self.history_window.activateWindow()

    def _insert_again(self, text: str) -> None:
        hwnd = self._last_external_hwnd()
        ctx = FocusContext(hwnd=hwnd, process=self._last_foreground_process)
        threading.Thread(target=lambda: self.injector.insert(text, ctx), daemon=True).start()

    def _last_external_hwnd(self) -> int:
        return self._target_hwnd

    def show_settings(self, page: str | None = None) -> SettingsWindow:
        w = SettingsWindow(self.loaded, self._settings_services())
        self.settings_window = w
        w.saved.connect(self._save_and_apply)
        if page:
            for i in range(w.nav.count()):
                if w.nav.item(i).text() == page:
                    w.nav.setCurrentRow(i)
        from sayso.ui import theme

        w.show()
        theme.style_title_bar(w)
        w.raise_()
        w.activateWindow()
        if page == "Diagnostics":
            w.run_diagnostics()
        return w

    def _settings_services(self) -> SettingsServices:
        from sayso.winsys import autostart

        def hotkeys_paused(paused: bool) -> None:
            if self._hotkeys:
                self._hotkeys.stop() if paused else self._hotkeys.start()

        def diagnostics() -> dict:
            from sayso.runtime_probes import build_probes

            return capabilities.probe(self.settings, self.paths, probes=build_probes(self.stt, self.llm)).to_dict()

        return SettingsServices(
            devices=AudioCapture.devices, stt_status=self.stt.status, diagnostics=diagnostics,
            test_provider=self._test_provider, calibrate=self._calibrate, download_model=self._download_model,
            last_foreground_process=lambda: self._last_foreground_process, pause_hotkeys=hotkeys_paused,
            autostart_get=lambda: _safe(autostart.is_enabled, False), autostart_set=self._set_autostart,
            secret_present=self.creds.has, secret_set=self.creds.set, data_dir=str(self.paths.data_dir),
            delete_history=self.history.clear, fix_hints=FIX_HINTS)

    def _set_autostart(self, on: bool) -> None:
        import sys

        from sayso.winsys import autostart

        try:
            if on:
                autostart.enable(sys.executable)
            else:
                autostart.disable()
        except Exception:
            log.warning("could not change start-with-Windows", exc_info=True)

    def _test_provider(self, name: str, cfg: ProviderSettings, key: str | None) -> tuple[bool, int, str]:
        from sayso.llm.registry import create_provider


        def secrets(ref: str) -> str | None:
            return key or self.creds.get(ref)

        provider = create_provider(name, cfg, secrets)
        t0 = time.perf_counter()
        res = provider.rewrite("hey can you tell john I'll be late", Mode.CHAT, PromptContext(), share_context=False,
                               timeout=max(6.0, self.settings.llm.timeout_s))
        provider.close()
        return bool(res.text), int((time.perf_counter() - t0) * 1000), res.text[:120]

    def _calibrate(self) -> float | None:
        cap = AudioCapture(self.settings.audio.sample_rate, self.settings.audio.device, max_seconds=5)
        try:
            cap.start()
            time.sleep(2.0)
            clip = cap.stop()
        except MicrophoneUnavailable:
            return None
        finally:
            cap.close()
        n = clip.sample_rate * 30 // 1000
        levels = [frame_db(clip.samples[i:i + n]) for i in range(0, len(clip.samples) - n, n)]
        return sorted(levels)[len(levels) // 2] if levels else None

    def _download_model(self, model: str, progress: Callable[[float], None]) -> str:
        from faster_whisper import download_model  # type: ignore[import-not-found]

        progress(0.05)
        download_model(model, cache_dir=str(self.paths.models_dir))
        progress(1.0)
        return f"Downloaded {model}"

    # -- warm-up

    def _warm_up(self) -> None:
        attempts = self.stt.warm_up()
        engines = ", ".join(f"{n}: {e}" for n, e in attempts)
        self._warm.emit(engines)

    def _on_warm(self, skipped: str) -> None:
        if not self.tray:
            return
        ready = [n for n, s in self.stt.status() if s == "ready"]
        providers = [n for n, ok, _ in self.llm.status if ok]
        self.tray.set_tooltip(f"Sayso · {ready[0] if ready else 'no speech engine'} · {providers[0] if providers else 'offline'}\n"
                              f"Hold {self.settings.hotkeys.push_to_talk} to dictate")
        if not ready:
            self.tray.notify("Sayso", "No speech engine is ready. Open Settings > Diagnostics.", True)


class _Cancelled(Exception):
    pass


def _safe(fn: Callable[[], bool], default: bool) -> bool:
    try:
        return fn()
    except Exception:
        return default
