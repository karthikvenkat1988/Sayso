import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QComboBox, QLineEdit  # noqa: E402

from sayso.core.config import LoadedSettings, Settings  # noqa: E402
from sayso.core.history import History  # noqa: E402
from sayso.ui import icons, theme  # noqa: E402
from sayso.ui.history_window import HistoryWindow  # noqa: E402
from sayso.ui.overlay import Overlay, OverlayState  # noqa: E402
from sayso.ui.settings_window import LOCKED_TIP, SettingsServices, SettingsWindow  # noqa: E402
from sayso.ui.tray import Tray  # noqa: E402
from sayso.ui.waveform import Waveform, WaveMode  # noqa: E402


@pytest.fixture(autouse=True)
def styled(qapp):
    theme.apply(qapp)


def test_overlay_states_and_api(qtbot):
    o = Overlay()
    qtbot.addWidget(o)
    for state in OverlayState:
        o.set_state(state, "message" if state is OverlayState.ERROR else "")
    o.set_state(OverlayState.RECORDING)
    assert o.isVisible() and o.state is OverlayState.RECORDING
    for lvl in (0.0, 0.4, 1.5):
        o.set_level(lvl)
    o.set_preview("hello there")
    o.append_preview(" and more " * 20)
    o.set_mode("Email")
    o.set_confidence(0.7)
    o.set_latency(1234)
    assert o.latency.text() == "1.2 s" and o.ring.isVisible()
    o.set_confidence(None)
    assert not o.ring.isVisible()
    o.set_state(OverlayState.ALWAYS_LISTENING)
    assert o.width() < 200 and not o.wave.isVisible()
    img = QImage(o.size(), QImage.Format.Format_ARGB32)
    o.render(img)
    assert not img.isNull()


def test_overlay_never_takes_focus_flags(qtbot):
    from PySide6.QtCore import Qt

    o = Overlay()
    qtbot.addWidget(o)
    flags = o.windowFlags()
    for f in (Qt.WindowType.WindowStaysOnTopHint, Qt.WindowType.WindowDoesNotAcceptFocus,
              Qt.WindowType.WindowTransparentForInput, Qt.WindowType.FramelessWindowHint):
        assert flags & f


def test_waveform_modes_paint(qtbot):
    w = Waveform()
    qtbot.addWidget(w)
    w.show()
    for mode in WaveMode:
        w.set_mode(mode)
        for _ in range(5):
            w.push_level(0.8)
            w._tick()
        w.grab()
    assert w._timer.isActive()
    w.hide()
    assert not w._timer.isActive()


def test_icons_render(qapp):
    assert not icons.icon().isNull()
    for badge in (None, "recording", "offline"):
        assert not icons.render(32, badge, grey=badge is None).isNull()


def test_settings_builds_from_defaults_and_round_trips(qtbot):
    w = SettingsWindow(LoadedSettings(Settings(), set(), False))
    qtbot.addWidget(w)
    assert w.collect() == Settings()
    assert w.nav.count() == 9


def test_settings_edits_flow_into_settings(qtbot):
    w = SettingsWindow(LoadedSettings(Settings(), set(), False))
    qtbot.addWidget(w)
    w.vocab.add_row("say so", "Sayso")
    w.snippets.add_row("my sig", "Best, K")
    w.vad.setValue(-50)
    w.stt_order.list.item(0).setCheckState(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.CheckState.Unchecked)
    s = w.collect()
    assert s.vocabulary == {"say so": "Sayso"} and s.snippets == {"my sig": "Best, K"}
    assert s.audio.vad_threshold_db == -50
    assert "faster_whisper" not in s.stt.engines


def test_locked_keys_disabled_and_kept(qtbot):
    base = Settings()
    base.privacy.offline_only = True
    loaded = LoadedSettings(base, {"privacy.offline_only", "llm.chain"}, True)
    w = SettingsWindow(loaded)
    qtbot.addWidget(w)
    locked = [wd for d, _, _, wd in w._bindings if d == "privacy.offline_only"][0]
    assert not locked.isEnabled() and locked.toolTip() == LOCKED_TIP
    assert w.collect().privacy.offline_only is True
    assert w.collect().llm.chain == base.llm.chain


def test_save_emits_and_stores_keys(qtbot):
    stored = {}
    svc = SettingsServices(secret_set=lambda ref, v: stored.__setitem__(ref, v))
    w = SettingsWindow(LoadedSettings(Settings(), set(), False), svc)
    qtbot.addWidget(w)
    w.chain_list.list.setCurrentRow(0)
    w.p_key.setText("")
    w.p_key.textEdited.emit("sk-test")
    with qtbot.waitSignal(w.saved) as blocker:
        w.save()
    assert isinstance(blocker.args[0], Settings)
    assert stored == {"llm.anthropic": "sk-test"}


def test_diagnostics_page_renders(qtbot):
    svc = SettingsServices(diagnostics=lambda: {"microphone": ["blocked", "denied"], "os": "Win", "stt_engines": {"a": ["ok", ""]}},
                           fix_hints={"microphone": "Turn it on"})
    w = SettingsWindow(LoadedSettings(Settings(), set(), False), svc)
    qtbot.addWidget(w)
    w.run_diagnostics()
    texts = [w.diag.item(i).text() for i in range(w.diag.count())]
    assert any("✕" in t and "Turn it on" in t for t in texts) and any("a ok" in t for t in texts)


def test_device_combo_stores_none_for_default(qtbot):
    svc = SettingsServices(devices=lambda: [("3", "USB Mic")])
    w = SettingsWindow(LoadedSettings(Settings(), set(), False), svc)
    qtbot.addWidget(w)
    assert w.collect().audio.device is None
    combo = [wd for d, _, _, wd in w._bindings if d == "audio.device"][0]
    assert isinstance(combo, QComboBox) and combo.count() == 2
    combo.setCurrentIndex(1)
    assert w.collect().audio.device == "3"
    assert isinstance(w.findChildren(QLineEdit)[0], QLineEdit)


def test_history_window_lists_and_searches(qtbot, tmp_path):
    h = History(tmp_path / "h.db")
    for t in ("alpha text", "beta text"):
        h.add(app="notepad", mode="chat_mode", transcript="raw", text=t, stt_engine="f", llm_provider="p",
              latency_ms=900, confidence=None)
    w = HistoryWindow(h)
    qtbot.addWidget(w)
    assert w.list.count() == 2 and "2 dictations" in w.footer.text()
    w.search.setText("alpha")
    w.refresh()
    assert w.list.count() == 1
    w.list.setCurrentRow(0)
    got = []
    w.insert_again.connect(got.append)
    w.insert_btn.click()
    assert got == ["alpha text"]
    w.delete_btn.click()
    assert w.list.count() == 0


def test_tray_menu(qtbot):
    t = Tray(show_always_listening=True, offline_locked=True, managed=True)
    texts = [a.text() for a in t.menu.actions()]
    assert "Settings…" in texts and "Managed by your organization" in texts
    assert not t.offline_action.isEnabled()
    got = []
    t.mode_chosen.connect(got.append)
    t.mode_actions[list(t.mode_actions)[2]].trigger()
    assert got
    t.set_state(recording=True)
    assert t.start_action.text() == "Stop dictation"
