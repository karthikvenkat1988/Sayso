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
