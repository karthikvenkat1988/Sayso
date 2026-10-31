from sayso.core.config import InjectionSettings
from sayso.core.context import FocusContext
from sayso.winsys.injection import InjectionFailed, InjectionMethod, Injector


class Rec(InjectionMethod):
    def __init__(self, name, fail=None):
        self.name, self.fail, self.calls = name, fail, []

    def insert(self, text, ctx, replace_selection):
        self.calls.append((text, replace_selection))
        if self.fail:
            raise self.fail


def build(settings=None, **fails):
    methods = {n: Rec(n, fails.get(n)) for n in ("paste", "accessibility", "keyboard", "clipboard")}
    prepared = []
    inj = Injector(
        settings or InjectionSettings(),
        methods=methods,
        prepare=prepared.append,
        clipboard_ok=lambda: True,
        uia_ok=lambda: False,
        remote=lambda: False,
    )
    return inj, methods, prepared


CTX = FocusContext(hwnd=7, process="notepad", control_class="Edit")


def test_first_method_wins():
    inj, m, prepared = build()
    r = inj.insert("hi", CTX, replace_selection=True)
    assert r.ok and r.method == "paste" and r.tried == [] and not r.needs_manual_paste
    assert m["paste"].calls == [("hi", True)] and prepared == [CTX]


def test_falls_through_failures_in_order():
    inj, m, _ = build(paste=InjectionFailed("clipboard busy"), accessibility=OSError("x"))
    r = inj.insert("hi", CTX)
    assert r.method == "keyboard" and [t[0] for t in r.tried] == ["paste", "accessibility"]
    assert r.tried[0][1] == "clipboard busy"


def test_clipboard_last_resort_needs_manual_paste():
    inj, m, _ = build(
        paste=InjectionFailed("a"), accessibility=InjectionFailed("b"), keyboard=InjectionFailed("c")
    )
    r = inj.insert("hi", CTX)
    assert r.method == "clipboard" and r.ok and r.needs_manual_paste


def test_elevated_target_goes_straight_to_clipboard():
    inj, m, _ = build()
    r = inj.insert("hi", FocusContext(process="notepad", is_elevated_target=True))
    assert r.method == "clipboard" and m["paste"].calls == []


def test_everything_failing_reports_not_ok():
    inj, _, _ = build(
        paste=InjectionFailed("a"),
        accessibility=InjectionFailed("b"),
        keyboard=InjectionFailed("c"),
        clipboard=InjectionFailed("d"),
    )
    r = inj.insert("hi", CTX)
    assert not r.ok and r.method == "none" and len(r.tried) == 4


def test_configured_method_and_prepare_failure_ignored():
    s = InjectionSettings(method="keyboard")
    inj, m, _ = build(s)
    inj._prepare = lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    assert inj.insert("x", CTX).method == "keyboard"


class FakeClipboard:
    """Stands in for the Win32 clipboard: one text slot and a sequence number."""

    class ClipboardBusy(Exception):
        pass

    def __init__(self, copied="the selection", fail_get=False):
        self.text, self.seq, self.copied, self.fail_get = "user's clipboard", 1, copied, fail_get
        self.restored = 0
        outer = self

        class Snap:
            saved = None

            @classmethod
            def take(cls):
                s = cls()
                s.saved = outer.text
                return s

            def restore(self):
                outer.text, outer.seq = self.saved, outer.seq + 1
                outer.restored += 1

        self.ClipboardSnapshot = Snap

    def clear(self):
        self.text, self.seq = None, self.seq + 1

    def sequence_number(self):
        return self.seq

    def get_text(self):
        if self.fail_get:
            raise OSError("read failed")
        return self.text

    def ctrl_c(self, events):
        if self.copied is not None:
            self.text, self.seq = self.copied, self.seq + 1
        return len(events)


def _copy_injector(monkeypatch, cb, order):
    from sayso.winsys import injection

    monkeypatch.setattr(injection, "clipboard", cb)
    monkeypatch.setattr(
        injection.win32, "send_key_events", lambda ev: (order.append("ctrl+c"), cb.ctrl_c(ev))[1]
    )
    inj, _, _ = build()
    inj._wait_modifiers = lambda: order.append("wait")
    return inj


def test_copy_selection_waits_for_modifiers_and_restores_clipboard(monkeypatch):
    cb, order = FakeClipboard(), []
    inj = _copy_injector(monkeypatch, cb, order)
    assert inj.copy_selection() == "the selection"
    assert order == ["wait", "ctrl+c"]  # Shift/Alt from the shortcut must be up before Ctrl+C is sent
    assert cb.text == "user's clipboard" and cb.restored == 1


def test_copy_selection_restores_clipboard_when_reading_fails(monkeypatch):
    cb, order = FakeClipboard(fail_get=True), []
    inj = _copy_injector(monkeypatch, cb, order)
    assert inj.copy_selection() is None
    assert cb.text == "user's clipboard"


def test_copy_selection_nothing_selected(monkeypatch):
    cb, order = FakeClipboard(copied=None), []
    inj = _copy_injector(monkeypatch, cb, order)
    assert inj.copy_selection() is None and cb.text == "user's clipboard"
