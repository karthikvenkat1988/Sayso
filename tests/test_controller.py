import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import numpy as np  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402

from sayso.audio.capture import MicrophoneUnavailable  # noqa: E402
from sayso.core.config import LoadedSettings, Settings, save_settings  # noqa: E402
from sayso.core.context import FocusContext  # noqa: E402
from sayso.core.history import History  # noqa: E402
from sayso.core.pipeline import Pipeline  # noqa: E402
from sayso.llm.registry import ProviderChain  # noqa: E402
from sayso.stt.registry import NoEngineAvailable, SttChain  # noqa: E402
from sayso.ui.controller import Controller, describe_error  # noqa: E402
from sayso.ui.overlay import OverlayState  # noqa: E402
from sayso.winsys.credentials import CredentialStore, MemoryBackend  # noqa: E402
from sayso.winsys.injection import InsertReport  # noqa: E402

from .conftest import FakeProvider, FakeSTT, make_clip  # noqa: E402


class FakeHotkeys(QObject):
    started = Signal(str, bool)
    stopped = Signal()
    cancelled = Signal()
    command_engaged = Signal()
    always_listening_toggled = Signal()
    backend_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.processing = []
        self.idle = 0

    def start(self): ...
    def stop(self): ...
    def reconfigure(self, *a): ...
    def set_processing(self, busy):
        self.processing.append(busy)

    def force_idle(self):
        self.idle += 1


class FakeAudio:
    on_level = None
    on_frame = None

    def __init__(self, clip, fail=None):
        self.clip, self.fail, self.started, self.closed = clip, fail, 0, 0

    def start(self):
        if self.fail:
            raise self.fail
        self.started += 1

    def stop(self):
        return self.clip

    def cancel(self):
        self.cancelled = getattr(self, "cancelled", 0) + 1

    def close(self):
        self.closed += 1

    def open(self): ...


class FakeInjector:
    def __init__(self, ok=True, manual=False):
        self.inserted, self.ok, self.manual = [], ok, manual
        self.settings = None

    def insert(self, text, ctx, *, replace_selection=False):
        self.inserted.append((text, replace_selection))
        return InsertReport("clipboard" if self.manual else "paste", self.ok, 12, [], self.manual)

    def copy_selection(self):
        return "selected text"


@pytest.fixture
def make(qtbot, tmp_paths, monkeypatch):
    save_settings(Settings(), tmp_paths.settings_file)
    made = []

    def build(
        text="please send the quarterly report to the finance team before friday",
        clip=None,
        ctx=None,
        audio_fail=None,
        injector=None,
        provider=None,
        settings=None,
    ):
        loaded = LoadedSettings(settings or Settings(), set(), False)
        hist = History(tmp_paths.history_db)
        hk, audio = FakeHotkeys(), FakeAudio(clip or make_clip(), audio_fail)
        inj = injector or FakeInjector()
        c = Controller(
            qtbot.app
            if hasattr(qtbot, "app")
            else __import__("PySide6.QtWidgets", fromlist=["x"]).QApplication.instance(),
            tmp_paths,
            loaded,
            CredentialStore(tmp_paths, backend=MemoryBackend()),
            hist,
            hotkeys=hk,
            audio=audio,
            injector=inj,
            capture_context=lambda hwnd: ctx or FocusContext(hwnd=hwnd, process="notepad"),
            foreground=lambda: 42,
            enable_tray=False,
        )
        prov = provider or FakeProvider("ai", "Polished text.")
        stt = SttChain([("fake", lambda: FakeSTT("fake", text))])
        c.pipeline = Pipeline(
            stt,
            ProviderChain(c.settings.llm, lambda r: None, factory=lambda n, cfg, s: prov),
            lambda: c.settings,
        )
        monkeypatch.setattr(c, "_warm_up", lambda: None)
        c.start()
        made.append(c)
        return c, hk, audio, inj, hist

    yield build
    for c in made:
        c.shutdown()


def test_push_to_talk_end_to_end(qtbot, make):
    c, hk, audio, inj, hist = make()
    hk.started.emit("ptt", False)
    assert c._recording and c.overlay.state is OverlayState.RECORDING and audio.started == 1
    with qtbot.waitSignal(c.dictated, timeout=5000) as sig:
        hk.stopped.emit()
    assert not c._recording and audio.closed >= 1
    assert inj.inserted == [("Polished text.", False)]
    assert sig.args[0].text == "Polished text."
    qtbot.waitUntil(lambda: c.overlay.state is OverlayState.SUCCESS and not c.busy, timeout=3000)
    assert "Inserted" in c.overlay.text.text()
    assert hk.processing[0] is True and hk.processing[-1] is False
    items = hist.recent()
    assert len(items) == 1 and items[0].text == "Polished text." and items[0].app == "notepad"
    assert c.metrics.median_total_ms() is not None


def test_command_mode_replaces_selection(qtbot, make):
    c, hk, audio, inj, _ = make(text="make this friendlier please and thanks")
    hk.started.emit("ptt", True)
    assert c.overlay.state is OverlayState.COMMAND
    with qtbot.waitSignal(c.dictated, timeout=5000):
        hk.stopped.emit()
    assert inj.inserted == [("Polished text.", True)]


def test_selection_copied_when_context_has_none(qtbot, make):
    seen = []

    class Spy(FakeProvider):
        def rewrite(self, transcript, mode, ctx, **kw):
            seen.append(ctx.selection)
            return super().rewrite(transcript, mode, ctx, **kw)

    c, hk, *_ = make(text="make this friendlier please and thanks", provider=Spy("ai", "ok"))
    hk.started.emit("ptt", True)
    with qtbot.waitSignal(c.dictated, timeout=5000):
        hk.stopped.emit()
    assert seen == ["selected text"]


def test_silence_shows_message_and_inserts_nothing(qtbot, make, silence_clip):
    c, hk, _, inj, hist = make(clip=silence_clip)
    hk.started.emit("toggle", False)
    assert c.overlay.state is OverlayState.HANDS_FREE
    hk.stopped.emit()
    qtbot.waitUntil(lambda: c.overlay.state is OverlayState.ERROR, timeout=5000)
    assert "catch" in c.overlay.text.text() and inj.inserted == [] and hist.recent() == []


def test_microphone_error_is_reported(qtbot, make):
    c, hk, *_ = make(audio_fail=MicrophoneUnavailable("Microphone access is off."))
    hk.started.emit("ptt", False)
    assert c.overlay.state is OverlayState.ERROR and not c._recording and hk.idle == 1
    assert "Microphone" in c.overlay.text.text()


def test_clipboard_fallback_message(qtbot, make):
    c, hk, *_ = make(injector=FakeInjector(manual=True))
    hk.started.emit("ptt", False)
    with qtbot.waitSignal(c.dictated, timeout=5000):
        hk.stopped.emit()
    qtbot.waitUntil(lambda: c.overlay.state is OverlayState.SUCCESS)
    assert "Press Ctrl+V" in c.overlay.text.text()


def test_elevated_window_message(qtbot, make):
    ctx = FocusContext(process="notepad", is_elevated_target=True)
    c, hk, *_ = make(injector=FakeInjector(manual=True), ctx=ctx)
    hk.started.emit("ptt", False)
    with qtbot.waitSignal(c.dictated, timeout=5000):
        hk.stopped.emit()
    qtbot.waitUntil(lambda: "admin" in c.overlay.text.text())


def test_insert_failure_is_an_error(qtbot, make):
    c, hk, *_ = make(injector=FakeInjector(ok=False))
    hk.started.emit("ptt", False)
    hk.stopped.emit()
    qtbot.waitUntil(lambda: c.overlay.state is OverlayState.ERROR, timeout=5000)
    assert "History" in c.overlay.text.text()


def test_cancel_discards_result(qtbot, make):
    c, hk, audio, inj, _ = make()
    hk.started.emit("ptt", False)
    hk.cancelled.emit()
    assert not c._recording and c.overlay.state is OverlayState.HIDDEN and inj.inserted == []


def test_paused_ignores_hotkeys_and_second_start_is_ignored(qtbot, make):
    c, hk, audio, *_ = make()
    c._set_paused(True)
    hk.started.emit("ptt", False)
    assert not c._recording
    c._set_paused(False)
    hk.started.emit("ptt", False)
    hk.started.emit("ptt", False)
    assert audio.started == 1


def test_blocked_app_never_inserts(qtbot, make):
    c, hk, _, inj, _ = make(ctx=FocusContext(process="KeePass"))
    hk.started.emit("ptt", False)
    hk.stopped.emit()
    qtbot.waitUntil(lambda: c.overlay.state is OverlayState.ERROR, timeout=5000)
    assert "Not dictating" in c.overlay.text.text() and inj.inserted == []


def test_always_listening_segment_is_processed(qtbot, make):
    from sayso.audio.vad import VadEvent, VadEventKind

    c, hk, audio, inj, _ = make()
    c.set_always_listening(True)
    assert c.overlay.state is OverlayState.ALWAYS_LISTENING and c._vad is not None
    c._vad = type(
        "V",
        (),
        {
            "process": lambda self, f: [
                VadEvent(VadEventKind.SPEECH_START),
                VadEvent(VadEventKind.SPEECH_END, make_clip(1.0).samples),
            ],
            "reset": lambda self: None,
        },
    )()
    with qtbot.waitSignal(c.dictated, timeout=5000):
        c._on_frame(np.zeros(480, dtype="float32"))
    assert inj.inserted
    c.set_always_listening(False)
    assert not c._always_on


def test_always_listening_blocked_by_policy(qtbot, make):
    s = Settings()
    s.activation.always_listening_allowed = False
    c, *_ = make(settings=s)
    c.set_always_listening(True)
    assert not c._always_on


def test_describe_error_messages():
    assert "Microphone" in describe_error(MicrophoneUnavailable("Microphone access is off."))
    assert "speech engine" in describe_error(NoEngineAvailable([("a", "b")]))
    assert "wrong" in describe_error(RuntimeError("secret dictated text"))
    assert "secret" not in describe_error(RuntimeError("secret dictated text"))


def test_outcome_of_cancelled_job_does_not_release_a_newer_job(qtbot, make):
    import threading

    from sayso.ui.controller import JobOutcome

    c, hk, *_ = make()
    old, new = threading.Event(), threading.Event()
    c._inflight = [new]  # cancel() cleared the old job's token, then a new dictation was submitted
    c._on_outcome(JobOutcome(cancelled=True, token=old))
    assert c._inflight == [new] and c.busy


def test_start_ignored_while_busy_resets_the_hotkey_machine(qtbot, make):
    import threading

    c, hk, audio, *_ = make()
    c._inflight = [threading.Event()]
    hk.started.emit("toggle", False)
    assert not c._recording and audio.started == 0 and hk.idle == 1


def test_history_updates_when_overlay_is_off(qtbot, make):
    s = Settings()
    s.general.show_overlay = False
    c, hk, *_ = make(settings=s)
    hk.started.emit("ptt", False)
    with qtbot.waitSignal(c.dictated, timeout=5000):
        hk.stopped.emit()


def test_always_listening_survives_settings_reload(qtbot, make):
    c, hk, audio, *_ = make()
    fresh = []

    def new_audio():
        a = FakeAudio(make_clip())
        fresh.append(a)
        return a

    c._audio_override = None
    c._new_audio = new_audio
    c.set_always_listening(True)
    c.reload_settings()
    assert c._always_on and fresh and c.audio is fresh[-1]
    assert c.audio.on_frame == c._on_frame and c.audio.started == 1


def test_turning_off_always_listening_keeps_a_push_to_talk_recording(qtbot, make):
    c, hk, audio, inj, _ = make()
    c.set_always_listening(True)
    hk.started.emit("ptt", False)
    c.set_always_listening(False)
    assert c._recording and not getattr(audio, "cancelled", 0)
    with qtbot.waitSignal(c.dictated, timeout=5000):
        hk.stopped.emit()
    assert inj.inserted
